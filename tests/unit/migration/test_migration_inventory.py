import hashlib
from pathlib import Path

from seh.migration import inventory
from seh.migration.inventory import KnownPath, detect_v1, take_inventory


def test_real_known_paths_json_lists_56_paths_with_sha256() -> None:
    baseline_ref, known = inventory.load_known_paths()

    assert baseline_ref == "4c5ac19"
    assert len(known) == 56
    assert known[".claude/skills/brainstorm/SKILL.md"].kind == "skill"
    assert len(known[".claude/skills/brainstorm/SKILL.md"].sha256) == 64


def test_inventory_reports_existing_known_file_with_its_sha256(tmp_path: Path, monkeypatch) -> None:
    content = b"v1 agent body"
    sha = hashlib.sha256(content).hexdigest()
    (tmp_path / ".claude/agents").mkdir(parents=True)
    (tmp_path / ".claude/agents/fixer.md").write_bytes(content)
    known = KnownPath(kind="agent", v2_action="REWRITE", sha256=sha)
    monkeypatch.setattr(
        inventory,
        "load_known_paths",
        lambda: (
            "base",
            {".claude/agents/fixer.md": known, ".claude/agents/gone.md": known},
        ),
    )

    entries = {e.path: e for e in take_inventory(tmp_path)}

    assert entries[".claude/agents/fixer.md"].exists is True
    assert entries[".claude/agents/fixer.md"].sha256 == sha
    assert entries[".claude/agents/fixer.md"].known == known
    assert entries[".claude/agents/gone.md"].exists is False


def test_inventory_reports_symlink_without_following_it(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / ".claude/skills").mkdir(parents=True)
    (tmp_path / ".agents").mkdir()
    (tmp_path / ".agents/skills").symlink_to("../.claude/skills")
    monkeypatch.setattr(inventory, "load_known_paths", lambda: ("base", {}))

    entries = {e.path: e for e in take_inventory(tmp_path)}

    link = entries[".agents/skills"]
    assert link.exists is True
    assert link.is_symlink is True
    assert link.link_target == "../.claude/skills"
    assert link.sha256 is None


def test_inventory_lists_existing_generated_targets_only(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / ".opencode/plugins").mkdir(parents=True)
    (tmp_path / ".opencode/plugins/x.ts").write_text("x")
    monkeypatch.setattr(inventory, "load_known_paths", lambda: ("base", {}))

    entries = take_inventory(tmp_path)

    assert [e.path for e in entries] == [".opencode"]
    assert entries[0].sha256 is not None


def test_inventory_does_not_modify_the_repository(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / ".claude/agents").mkdir(parents=True)
    (tmp_path / ".claude/agents/fixer.md").write_text("x")
    (tmp_path / ".codex").mkdir()
    monkeypatch.setattr(inventory, "load_known_paths", lambda: ("base", {}))
    before = sorted(str(p) for p in tmp_path.rglob("*"))

    take_inventory(tmp_path)

    assert sorted(str(p) for p in tmp_path.rglob("*")) == before


def test_detect_v1_true_when_a_known_skill_exists(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / ".claude/skills/x").mkdir(parents=True)
    (tmp_path / ".claude/skills/x/SKILL.md").write_text("x")
    known = KnownPath(kind="skill", v2_action="DELETE", sha256="0" * 64)
    monkeypatch.setattr(
        inventory, "load_known_paths", lambda: ("base", {".claude/skills/x/SKILL.md": known})
    )

    assert detect_v1(tmp_path) is True


def test_detect_v1_false_when_only_memory_kind_exists(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / ".agent-memory").mkdir()
    (tmp_path / ".agent-memory/MEMORY.md").write_text("x")
    known = KnownPath(kind="memory", v2_action="KEEP", sha256="0" * 64)
    monkeypatch.setattr(
        inventory, "load_known_paths", lambda: ("base", {".agent-memory/MEMORY.md": known})
    )

    assert detect_v1(tmp_path) is False
