import json
from pathlib import Path

import pytest

from seh.authoring.inventory import collect_inventory


def _snapshot(root: Path) -> dict[str, bytes]:
    return {str(p): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def test_collect_finds_skills_agents_tools_cli_and_builtins(tmp_path: Path) -> None:
    skill_dir = tmp_path / ".claude" / "skills" / "work"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: work\ndescription: 実装依頼を処理する\n---\n本文\n", encoding="utf-8"
    )
    agents = tmp_path / ".claude" / "agents"
    agents.mkdir(parents=True)
    (agents / "reviewer.md").write_text(
        "---\nname: reviewer\ndescription: 差分をレビューする\n---\n本文\n", encoding="utf-8"
    )

    items = collect_inventory(tmp_path)

    found = {(i.kind, i.name) for i in items}
    assert ("skill", "work") in found
    assert ("agent", "reviewer") in found
    assert ("tool", "tests.run") in found
    assert ("cli", "sync") in found
    assert any(i.kind == "builtin" for i in items)
    work = next(i for i in items if i.kind == "skill" and i.name == "work")
    assert work.source == ".claude/skills/work/SKILL.md"
    assert work.description == "実装依頼を処理する"


def test_collect_reads_shared_agents_skill_from_other_host(tmp_path: Path) -> None:
    skill_dir = tmp_path / ".agents" / "skills" / "shared-one"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: shared-one\ndescription: 共有手順\n---\n本文\n", encoding="utf-8"
    )

    items = collect_inventory(tmp_path)

    assert ("skill", "shared-one") in {(i.kind, i.name) for i in items}


def test_collect_reads_project_mcp_server_names(tmp_path: Path) -> None:
    (tmp_path / ".mcp.json").write_text(
        json.dumps({"mcpServers": {"github": {"command": "x"}, "jira": {"command": "y"}}}),
        encoding="utf-8",
    )

    items = collect_inventory(tmp_path)

    mcp_names = {i.name for i in items if i.kind == "mcp"}
    assert mcp_names == {"github", "jira"}


def test_collect_ignores_malformed_mcp_json(tmp_path: Path) -> None:
    (tmp_path / ".mcp.json").write_text("{not json", encoding="utf-8")

    items = collect_inventory(tmp_path)

    assert [i for i in items if i.kind == "mcp"] == []


def test_collect_does_not_read_home_side_mcp_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    (home / ".claude.json").write_text(
        json.dumps({"mcpServers": {"homeonly": {"command": "z"}}}), encoding="utf-8"
    )
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.setenv("HOME", str(home))

    items = collect_inventory(project)

    assert "homeonly" not in {i.name for i in items}


def test_collect_is_read_only(tmp_path: Path) -> None:
    skill_dir = tmp_path / ".claude" / "skills" / "work"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("---\ndescription: d\n---\n本文\n", encoding="utf-8")
    (tmp_path / ".mcp.json").write_text('{"mcpServers": {"a": {}}}', encoding="utf-8")
    before = _snapshot(tmp_path)
    dirs_before = sorted(str(p) for p in tmp_path.rglob("*"))

    collect_inventory(tmp_path)

    assert _snapshot(tmp_path) == before
    assert sorted(str(p) for p in tmp_path.rglob("*")) == dirs_before
