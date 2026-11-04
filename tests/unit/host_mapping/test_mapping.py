import json

import pytest

from seh.contracts import CanonicalSpec, HostId, RenderContext
from seh.providers.hosts.antigravity import AntigravityHostAdapter
from seh.providers.hosts.claude import ClaudeHostAdapter
from seh.providers.hosts.codex import CodexHostAdapter
from seh.providers.hosts.opencode import OpenCodeHostAdapter
from seh.providers.hosts.permissions_map import map_permissions


@pytest.mark.parametrize(
    ("adapter", "host", "path"),
    [
        (ClaudeHostAdapter(), HostId.CLAUDE, ".claude/settings.json"),
        (CodexHostAdapter(), HostId.CODEX, ".codex/hooks.json"),
        (AntigravityHostAdapter(), HostId.ANTIGRAVITY, ".agents/hooks.json"),
        (OpenCodeHostAdapter(), HostId.OPENCODE, ".opencode/plugins/seh-guard.ts"),
    ],
)
def test_host_renders_hook(adapter, host, path, tmp_path):
    spec = CanonicalSpec(instructions="", skills=(), agents=(), rules=())
    plan = adapter.render(spec, RenderContext(tmp_path, (host,), "test"))
    change = next(c for c in plan.changes if c.path == path)
    assert b"seh hook" in change.content
    assert b"PreToolUse" in change.content
    if path.endswith(".json"):
        json.loads(change.content)


def test_unsupported_denial_is_an_error():
    result = map_permissions(HostId.CODEX, {"write": "deny"})
    assert result.diagnostics
    assert result.diagnostics[0].level.value == "ERROR"


def test_opencode_hook_passes_tool_arguments(tmp_path):
    spec = CanonicalSpec(instructions="", skills=(), agents=(), rules=())
    plan = OpenCodeHostAdapter().render(spec, RenderContext(tmp_path, (HostId.OPENCODE,), "test"))
    content = next(c.content for c in plan.changes if c.path.endswith("seh-guard.ts"))
    assert content is not None
    assert b"tool: input.tool" in content
    assert b"args: output.args" in content
    assert b"cwd: directory" in content


@pytest.mark.parametrize("host", [HostId.CODEX, HostId.ANTIGRAVITY])
def test_pretool_hook_fails_closed_if_installed_seh_cannot_start(host, tmp_path):
    import os
    import subprocess

    from seh.providers.hosts.hooks_map import render_hooks

    binary = tmp_path / "seh"
    binary.write_text("#!/bin/sh\necho broken >&2\nexit 1\n")
    binary.chmod(0o755)
    content = render_hooks(host)[0].content
    assert content is not None
    config = json.loads(content)
    hooks = config["seh" if host is HostId.ANTIGRAVITY else "hooks"]
    command = hooks["PreToolUse"][0]["hooks"][0]["command"]
    result = subprocess.run(
        ["sh", "-c", command],
        input="{}",
        text=True,
        capture_output=True,
        env={**os.environ, "PATH": str(tmp_path) + os.pathsep + os.environ["PATH"]},
        check=False,
    )
    if host is HostId.CODEX:
        assert result.returncode == 2
    else:
        assert json.loads(result.stdout)["decision"] == "deny"


def test_antigravity_hook_preserves_successful_decision(tmp_path):
    import os
    import subprocess

    from seh.providers.hosts.hooks_map import render_hooks

    binary = tmp_path / "seh"
    binary.write_text('#!/bin/sh\necho \'{"decision":"deny","reason":"policy"}\'\n')
    binary.chmod(0o755)
    content = render_hooks(HostId.ANTIGRAVITY)[0].content
    assert content is not None
    command = json.loads(content)["seh"]["PreToolUse"][0]["hooks"][0]["command"]
    result = subprocess.run(
        ["sh", "-c", command],
        input="{}",
        text=True,
        capture_output=True,
        env={**os.environ, "PATH": str(tmp_path) + os.pathsep + os.environ["PATH"]},
        check=False,
    )
    assert result.returncode == 0
    assert json.loads(result.stdout) == {"decision": "deny", "reason": "policy"}


def test_render_permission_denial_and_reject_unrepresentable(tmp_path):
    spec = CanonicalSpec(
        instructions="", skills=(), agents=(), rules=(), permissions={"write": "deny"}
    )
    claude = ClaudeHostAdapter().render(spec, RenderContext(tmp_path, (HostId.CLAUDE,), "test"))
    content = next(c.content for c in claude.changes if c.path == ".claude/settings.json")
    assert content is not None
    settings = json.loads(content)
    assert set(settings["permissions"]["deny"]) == {"Write", "Edit"}
    codex = CodexHostAdapter().render(spec, RenderContext(tmp_path, (HostId.CODEX,), "test"))
    assert any(
        d.code == "UNSUPPORTED_PERMISSION" and d.level.value == "ERROR" for d in codex.diagnostics
    )


def test_existing_settings_are_reported_as_conflict(tmp_path):
    from seh.sync import plan_sync

    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude/settings.json").write_text('{"other": true}')
    spec = CanonicalSpec(instructions="", skills=(), agents=(), rules=())
    plan = plan_sync(tmp_path, (HostId.CLAUDE,), spec=spec)
    assert any(c.path == ".claude/settings.json" for c in plan.conflicts)


@pytest.mark.parametrize("host", list(HostId))
def test_hook_snapshot(host):
    from pathlib import Path

    from seh.providers.hosts.hooks_map import render_hooks

    snapshot = Path(__file__).parent / "snapshots" / f"{host.value}.txt"
    assert render_hooks(host)[0].content == snapshot.read_bytes()


def test_antigravity_schema_and_claude_fail_closed():
    from seh.providers.hosts.hooks_map import render_hooks

    agy_content = render_hooks(HostId.ANTIGRAVITY)[0].content
    assert agy_content is not None
    agy = json.loads(agy_content)["seh"]
    assert agy["PreToolUse"][0]["hooks"][0]["type"] == "command"
    assert agy["SessionStart"][0]["type"] == "command"
    claude_content = render_hooks(HostId.CLAUDE)[0].content
    assert claude_content is not None
    claude = json.loads(claude_content)["hooks"]
    assert claude["PreToolUse"][0]["hooks"][0]["onFailure"] == "block"


def test_host_payloads_reach_policy():
    from seh.events import run_hook
    from seh.policy import Policy

    agy = {
        "toolCall": {"name": "run_command", "args": {"CommandLine": "rm -rf /"}},
        "workspacePaths": ["/"],
    }
    _, stdout, _ = run_hook(
        "PreToolUse",
        HostId.ANTIGRAVITY,
        json.dumps(agy).encode(),
        policy=Policy(),
        trace=None,
        unattended=True,
    )
    assert json.loads(stdout)["decision"] == "deny"
    opencode = {"tool": "bash", "args": {"command": "rm -rf /"}}
    code, _, _ = run_hook(
        "PreToolUse",
        HostId.OPENCODE,
        json.dumps(opencode).encode(),
        policy=Policy(),
        trace=None,
        unattended=True,
    )
    assert code == 2


def test_antigravity_target_file_is_checked():
    from seh.events import parse_hook_input

    payload = {
        "toolCall": {"name": "write_to_file", "args": {"TargetFile": ".claude/settings.json"}},
        "workspacePaths": ["/"],
    }
    result = parse_hook_input("PreToolUse", HostId.ANTIGRAVITY, json.dumps(payload).encode())
    assert result.paths == (".claude/settings.json",)


def test_antigravity_command_uses_tool_cwd():
    from pathlib import Path

    from seh.events import parse_hook_input

    payload = {
        "toolCall": {"name": "run_command", "args": {"CommandLine": "pwd", "Cwd": "/tmp/project"}},
        "workspacePaths": ["/workspace"],
    }
    result = parse_hook_input("PreToolUse", HostId.ANTIGRAVITY, json.dumps(payload).encode())
    assert result.cwd == Path("/tmp/project")
