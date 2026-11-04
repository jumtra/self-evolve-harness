import json
from pathlib import Path

import pytest

from seh.contracts import HostId
from seh.events import MalformedHookInput, parse_hook_input


def test_claude_bash_payload_yields_command_and_cwd() -> None:
    payload = json.dumps(
        {"tool_name": "Bash", "tool_input": {"command": "ls -la"}, "cwd": "/work/repo"}
    ).encode()

    inp = parse_hook_input("PreToolUse", HostId.CLAUDE, payload)

    assert inp.tool == "Bash"
    assert inp.command == "ls -la"
    assert inp.paths == ()
    assert inp.cwd == Path("/work/repo")
    assert inp.host == HostId.CLAUDE
    assert inp.event == "PreToolUse"


def test_claude_write_payload_yields_file_path() -> None:
    payload = json.dumps(
        {"tool_name": "Write", "tool_input": {"file_path": "src/a.py"}, "cwd": "/work"}
    ).encode()

    inp = parse_hook_input("PreToolUse", HostId.CLAUDE, payload)

    assert inp.command is None
    assert inp.paths == ("src/a.py",)


def test_claude_multiedit_payload_collects_every_edit_path() -> None:
    payload = json.dumps(
        {
            "tool_name": "MultiEdit",
            "tool_input": {
                "file_path": "a.py",
                "edits": [{"file_path": "b.py"}, {"file_path": "c.py"}],
            },
            "cwd": "/work",
        }
    ).encode()

    inp = parse_hook_input("PreToolUse", HostId.CLAUDE, payload)

    assert inp.paths == ("a.py", "b.py", "c.py")


def test_codex_path_key_is_accepted() -> None:
    payload = json.dumps(
        {"tool_name": "Edit", "tool_input": {"path": "x.txt"}, "cwd": "/work"}
    ).encode()

    inp = parse_hook_input("PreToolUse", HostId.CODEX, payload)

    assert inp.paths == ("x.txt",)
    assert inp.host == HostId.CODEX


def test_antigravity_camel_case_payload_is_normalized() -> None:
    payload = json.dumps(
        {
            "toolCall": {"name": "run_command", "args": {"command": "echo hi"}},
            "workspacePaths": ["/ws/project"],
        }
    ).encode()

    inp = parse_hook_input("PreToolUse", HostId.ANTIGRAVITY, payload)

    assert inp.tool == "run_command"
    assert inp.command == "echo hi"
    assert inp.cwd == Path("/ws/project")


def test_antigravity_file_path_variants_are_collected() -> None:
    payload = json.dumps(
        {
            "toolCall": {"name": "write_file", "args": {"filePath": "a.py"}},
            "workspacePaths": ["/ws"],
        }
    ).encode()

    inp = parse_hook_input("PreToolUse", HostId.ANTIGRAVITY, payload)

    assert inp.paths == ("a.py",)


def test_antigravity_without_tool_call_is_malformed() -> None:
    payload = json.dumps({"workspacePaths": ["/ws"]}).encode()

    with pytest.raises(MalformedHookInput):
        parse_hook_input("PreToolUse", HostId.ANTIGRAVITY, payload)


def test_antigravity_without_workspace_paths_is_malformed() -> None:
    payload = json.dumps({"toolCall": {"name": "x", "args": {}}}).encode()

    with pytest.raises(MalformedHookInput):
        parse_hook_input("PreToolUse", HostId.ANTIGRAVITY, payload)


def test_opencode_plugin_payload_is_normalized() -> None:
    payload = json.dumps(
        {"tool": "bash", "args": {"command": "make test"}, "cwd": "/oc/repo"}
    ).encode()

    inp = parse_hook_input("PreToolUse", HostId.OPENCODE, payload)

    assert inp.tool == "bash"
    assert inp.command == "make test"
    assert inp.cwd == Path("/oc/repo")


def test_opencode_edit_payload_yields_path() -> None:
    payload = json.dumps({"tool": "edit", "args": {"filePath": "z.py"}, "cwd": "/oc"}).encode()

    inp = parse_hook_input("PreToolUse", HostId.OPENCODE, payload)

    assert inp.paths == ("z.py",)


@pytest.mark.parametrize("host", list(HostId))
def test_invalid_json_is_malformed(host: HostId) -> None:
    with pytest.raises(MalformedHookInput):
        parse_hook_input("PreToolUse", host, b"{not json")


@pytest.mark.parametrize("host", list(HostId))
def test_non_object_json_is_malformed(host: HostId) -> None:
    with pytest.raises(MalformedHookInput):
        parse_hook_input("PreToolUse", host, b"[1, 2]")


def test_non_string_command_is_malformed() -> None:
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": 5}}).encode()

    with pytest.raises(MalformedHookInput):
        parse_hook_input("PreToolUse", HostId.CLAUDE, payload)
