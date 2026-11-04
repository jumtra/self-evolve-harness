import json

import pytest

from seh.contracts import HostId
from seh.events import MalformedHookInput, parse_hook_input, run_hook
from seh.policy import Policy


@pytest.mark.parametrize("host", [HostId.CLAUDE, HostId.CODEX])
def test_pretooluse_without_tool_name_is_malformed(host: HostId) -> None:
    payload = json.dumps({"tool_input": {"command": "ls"}, "cwd": "/"}).encode()

    with pytest.raises(MalformedHookInput):
        parse_hook_input("PreToolUse", host, payload)


def test_pretooluse_with_non_string_tool_name_is_blocked() -> None:
    payload = json.dumps({"tool_name": 3, "tool_input": {}, "cwd": "/"}).encode()

    code, _, stderr = run_hook(
        "PreToolUse", HostId.CLAUDE, payload, policy=Policy(), trace=None, unattended=False
    )

    assert code == 2
    assert stderr != ""


@pytest.mark.parametrize("key", ["command", "cmd", "script"])
def test_command_is_read_from_any_known_key(key: str) -> None:
    payload = json.dumps({"tool_name": "x", "tool_input": {key: "ls"}, "cwd": "/"}).encode()

    inp = parse_hook_input("PreToolUse", HostId.CODEX, payload)

    assert inp.command == "ls"


def test_antigravity_command_is_read_from_cmd_key() -> None:
    payload = json.dumps(
        {"toolCall": {"name": "x", "args": {"cmd": "ls"}}, "workspacePaths": ["/"]}
    ).encode()

    inp = parse_hook_input("PreToolUse", HostId.ANTIGRAVITY, payload)

    assert inp.command == "ls"


def test_paths_are_collected_recursively_from_path_like_keys() -> None:
    tool_input = {
        "notebook_path": "a.ipynb",
        "FilePath": "b.py",
        "nested": {"target_path": "c.py", "deeper": [{"file_path": "d.py"}]},
        "paths": ["e.py", "f.py"],
        "files": ["g.py"],
        "content": "not a path",
    }
    payload = json.dumps({"tool_name": "x", "tool_input": tool_input, "cwd": "/"}).encode()

    inp = parse_hook_input("PreToolUse", HostId.CLAUDE, payload)

    assert set(inp.paths) == {"a.ipynb", "b.py", "c.py", "d.py", "e.py", "f.py", "g.py"}
