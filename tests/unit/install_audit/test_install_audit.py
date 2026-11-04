import hashlib
import json
from pathlib import Path

import pytest

from seh.install_audit import Registration, collect_registrations, find_duplicates
from seh.ownership import OwnershipManifest

SEH_HOOK = "seh hook pre-tool-use"


def _snapshot(root: Path) -> dict[str, bytes]:
    return {str(p): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def test_seh_hook_and_v1_destructive_check_on_same_matcher_is_duplicate_hook(
    tmp_path: Path,
) -> None:
    v1_command = 'if echo "$CMD" | grep -q \'rm ' + "-rf'; then exit 2; fi"
    settings = {
        "hooks": {
            "PreToolUse": [
                {"matcher": "Bash", "hooks": [{"type": "command", "command": SEH_HOOK}]},
                {"matcher": "Bash", "hooks": [{"type": "command", "command": v1_command}]},
            ]
        }
    }
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "settings.json").write_text(json.dumps(settings), encoding="utf-8")

    duplicates = find_duplicates(collect_registrations(tmp_path))

    assert [(d.kind, d.severity, d.reason) for d in duplicates] == [
        ("hook", "ERROR", "DUPLICATE_HOOK")
    ]


def test_same_hook_command_registered_twice_is_duplicate_hook(tmp_path: Path) -> None:
    entry = {"matcher": "Bash", "hooks": [{"type": "command", "command": "echo audit"}]}
    settings = {"hooks": {"PreToolUse": [entry, entry]}}
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "settings.json").write_text(json.dumps(settings), encoding="utf-8")

    duplicates = find_duplicates(collect_registrations(tmp_path))

    assert [d.reason for d in duplicates] == ["DUPLICATE_HOOK"]


def test_seh_hook_alone_and_unrelated_hook_are_not_duplicates(tmp_path: Path) -> None:
    settings = {
        "hooks": {
            "PreToolUse": [
                {"matcher": "Bash", "hooks": [{"type": "command", "command": SEH_HOOK}]},
                {"matcher": "Bash", "hooks": [{"type": "command", "command": "echo hi"}]},
            ]
        }
    }
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "settings.json").write_text(json.dumps(settings), encoding="utf-8")

    assert find_duplicates(collect_registrations(tmp_path)) == []


def test_hook_is_attributed_to_seh_only_when_command_calls_seh(tmp_path: Path) -> None:
    settings = {
        "hooks": {
            "Stop": [
                {"hooks": [{"type": "command", "command": SEH_HOOK}]},
                {"hooks": [{"type": "command", "command": "echo hi"}]},
            ]
        }
    }
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "settings.json").write_text(json.dumps(settings), encoding="utf-8")

    regs = collect_registrations(tmp_path)

    assert sorted((r.kind, r.managed_by_seh) for r in regs) == [("hook", False), ("hook", True)]


def test_external_graphify_skill_without_name_clash_is_only_external_installer_warning(
    tmp_path: Path,
) -> None:
    (tmp_path / ".claude" / "skills" / "graphify").mkdir(parents=True)
    (tmp_path / ".claude" / "skills" / "graphify" / "SKILL.md").write_text("x", encoding="utf-8")
    (tmp_path / ".claude" / "skills" / "tdd").mkdir(parents=True)
    (tmp_path / ".claude" / "skills" / "tdd" / "SKILL.md").write_text("y", encoding="utf-8")
    content = b"y"
    manifest = OwnershipManifest()
    manifest.record(
        ".claude/skills/tdd/SKILL.md", hashlib.sha256(content).hexdigest(), "skills", "0"
    )
    manifest.save(tmp_path)

    duplicates = find_duplicates(collect_registrations(tmp_path))

    assert [(d.kind, d.key, d.severity, d.reason) for d in duplicates] == [
        ("skill", "graphify", "WARN", "EXTERNAL_INSTALLER_REGISTRATION")
    ]


def test_same_named_skill_in_another_host_dir_is_not_a_duplicate(
    tmp_path: Path,
) -> None:
    (tmp_path / ".claude" / "skills" / "review").mkdir(parents=True)
    (tmp_path / ".claude" / "skills" / "review" / "SKILL.md").write_text("a", encoding="utf-8")
    (tmp_path / ".claude" / "skills" / "review" / "extra.md").write_text("b", encoding="utf-8")
    manifest = OwnershipManifest()
    manifest.record(
        ".claude/skills/review/SKILL.md", hashlib.sha256(b"a").hexdigest(), "skills", "0"
    )
    manifest.save(tmp_path)
    (tmp_path / ".agents" / "skills" / "review").mkdir(parents=True)
    (tmp_path / ".agents" / "skills" / "review" / "SKILL.md").write_text("c", encoding="utf-8")

    duplicates = find_duplicates(collect_registrations(tmp_path))

    # 別ホスト（.agents）の非管理 skill とは衝突しない
    assert duplicates == []


def test_skill_name_clash_within_one_host_is_duplicate_skill(tmp_path: Path) -> None:
    (tmp_path / ".claude" / "skills" / "review").mkdir(parents=True)
    (tmp_path / ".claude" / "skills" / "review" / "SKILL.md").write_text("a", encoding="utf-8")
    regs = collect_registrations(tmp_path)
    seh_reg = Registration("claude", "skill", "review", ".claude/skills/review", True)

    duplicates = find_duplicates([*regs, seh_reg])

    assert [(d.kind, d.key, d.severity, d.reason) for d in duplicates] == [
        ("skill", "review", "ERROR", "DUPLICATE_SKILL")
    ]


def test_same_mcp_server_in_mcp_json_and_codex_config_is_duplicate_mcp(tmp_path: Path) -> None:
    (tmp_path / ".mcp.json").write_text(
        json.dumps({"mcpServers": {"docs": {"command": "x"}}}), encoding="utf-8"
    )
    (tmp_path / ".codex").mkdir()
    (tmp_path / ".codex" / "config.toml").write_text(
        '[mcp_servers.docs]\ncommand = "x"\n', encoding="utf-8"
    )

    duplicates = find_duplicates(collect_registrations(tmp_path))

    assert [(d.kind, d.key, d.severity, d.reason) for d in duplicates] == [
        ("mcp", "docs", "WARN", "DUPLICATE_MCP")
    ]


def test_opencode_plugin_and_mcp_are_collected(tmp_path: Path) -> None:
    (tmp_path / ".opencode" / "plugins").mkdir(parents=True)
    (tmp_path / ".opencode" / "plugins" / "guard.js").write_text("//", encoding="utf-8")
    (tmp_path / "opencode.json").write_text(json.dumps({"mcp": {"srv": {}}}), encoding="utf-8")

    regs = collect_registrations(tmp_path)

    assert sorted((r.host, r.kind, r.name) for r in regs) == [
        ("opencode", "mcp", "srv"),
        ("opencode", "plugin", "guard"),
    ]


def test_external_codegraph_mcp_is_external_installer_warning(tmp_path: Path) -> None:
    (tmp_path / ".mcp.json").write_text(
        json.dumps({"mcpServers": {"codegraph": {"command": "codegraph"}}}), encoding="utf-8"
    )

    duplicates = find_duplicates(collect_registrations(tmp_path))

    assert [(d.kind, d.severity, d.reason) for d in duplicates] == [
        ("mcp", "WARN", "EXTERNAL_INSTALLER_REGISTRATION")
    ]


def test_empty_project_has_no_registrations_or_duplicates(tmp_path: Path) -> None:
    assert collect_registrations(tmp_path) == []
    assert find_duplicates([]) == []


def test_collect_is_read_only_and_ignores_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    (home / ".claude.json").write_text(
        json.dumps({"mcpServers": {"homeonly": {"command": "x"}}}), encoding="utf-8"
    )
    monkeypatch.setenv("HOME", str(home))
    project = tmp_path / "project"
    (project / ".claude").mkdir(parents=True)
    (project / ".claude" / "settings.json").write_text(
        json.dumps({"hooks": {"Stop": [{"hooks": [{"command": "echo a"}]}]}}), encoding="utf-8"
    )
    before = _snapshot(project)

    regs = collect_registrations(project)

    assert [r.name for r in regs if r.kind == "mcp"] == []
    assert _snapshot(project) == before
