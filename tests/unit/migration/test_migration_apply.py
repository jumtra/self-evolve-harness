import hashlib
import os
from pathlib import Path

import pytest

from seh.migration import apply as apply_module
from seh.migration import inventory
from seh.migration.apply import PlanStale, apply_migration
from seh.migration.inventory import KnownPath
from seh.migration.planner import plan_migration
from seh.migration.rollback import rollback_migration


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def test_apply_deletes_planned_files_and_empty_v1_directories(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / ".claude/skills/brainstorm").mkdir(parents=True)
    (tmp_path / ".claude/skills/brainstorm/SKILL.md").write_bytes(b"v1")
    (tmp_path / ".claude/agents").mkdir()
    (tmp_path / ".claude/agents/fixer.md").write_bytes(b"agent")
    (tmp_path / ".claude/templates").mkdir()
    (tmp_path / ".claude/templates/keep.md").write_bytes(b"keep")
    known = {
        ".claude/skills/brainstorm/SKILL.md": KnownPath("skill", "DELETE", _sha(b"v1")),
        ".claude/agents/fixer.md": KnownPath("agent", "REWRITE", _sha(b"agent")),
        ".claude/templates/keep.md": KnownPath("template", "KEEP", _sha(b"keep")),
    }
    monkeypatch.setattr(inventory, "load_known_paths", lambda: ("base", known))
    plan = plan_migration(tmp_path)

    result = apply_migration(tmp_path, plan)

    assert not (tmp_path / ".claude/skills/brainstorm").exists()
    assert not (tmp_path / ".claude/agents/fixer.md").exists()
    assert (tmp_path / ".claude/templates/keep.md").read_bytes() == b"keep"
    assert sorted(result.deleted) == [
        ".claude/agents/fixer.md",
        ".claude/skills/brainstorm/SKILL.md",
    ]
    assert result.skipped == []
    assert result.snapshot_id


def test_unapproved_conflict_stays_and_approved_conflict_is_deleted(
    tmp_path: Path, monkeypatch
) -> None:
    (tmp_path / ".claude/agents").mkdir(parents=True)
    (tmp_path / ".claude/agents/fixer.md").write_bytes(b"edited1")
    (tmp_path / ".claude/agents/evolver.md").write_bytes(b"edited2")
    known = {
        ".claude/agents/fixer.md": KnownPath("agent", "REWRITE", _sha(b"orig")),
        ".claude/agents/evolver.md": KnownPath("agent", "REWRITE", _sha(b"orig")),
    }
    monkeypatch.setattr(inventory, "load_known_paths", lambda: ("base", known))
    plan = plan_migration(tmp_path)

    result = apply_migration(tmp_path, plan, approve_conflicts=[".claude/agents/evolver.md"])

    assert (tmp_path / ".claude/agents/fixer.md").read_bytes() == b"edited1"
    assert not (tmp_path / ".claude/agents/evolver.md").exists()
    assert result.deleted == [".claude/agents/evolver.md"]
    assert result.skipped == [".claude/agents/fixer.md"]


def test_file_changed_after_planning_aborts_everything_with_plan_stale(
    tmp_path: Path, monkeypatch
) -> None:
    (tmp_path / ".claude/agents").mkdir(parents=True)
    (tmp_path / ".claude/agents/fixer.md").write_bytes(b"orig")
    (tmp_path / ".claude/agents/evolver.md").write_bytes(b"orig")
    known = {
        ".claude/agents/fixer.md": KnownPath("agent", "DELETE", _sha(b"orig")),
        ".claude/agents/evolver.md": KnownPath("agent", "DELETE", _sha(b"orig")),
    }
    monkeypatch.setattr(inventory, "load_known_paths", lambda: ("base", known))
    plan = plan_migration(tmp_path)
    (tmp_path / ".claude/agents/evolver.md").write_bytes(b"changed after plan")

    with pytest.raises(PlanStale):
        apply_migration(tmp_path, plan)

    assert (tmp_path / ".claude/agents/fixer.md").read_bytes() == b"orig"
    assert (tmp_path / ".claude/agents/evolver.md").read_bytes() == b"changed after plan"


def test_failure_midway_restores_every_file(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / ".claude/agents").mkdir(parents=True)
    (tmp_path / ".claude/agents/a.md").write_bytes(b"a")
    (tmp_path / ".claude/agents/b.md").write_bytes(b"b")
    known = {
        ".claude/agents/a.md": KnownPath("agent", "DELETE", _sha(b"a")),
        ".claude/agents/b.md": KnownPath("agent", "DELETE", _sha(b"b")),
    }
    monkeypatch.setattr(inventory, "load_known_paths", lambda: ("base", known))
    plan = plan_migration(tmp_path)
    real_delete = apply_module.Transaction.delete

    def failing_delete(self: apply_module.Transaction, path: str) -> None:
        if path.endswith("b.md"):
            raise OSError("disk error")
        real_delete(self, path)

    monkeypatch.setattr(apply_module.Transaction, "delete", failing_delete)

    with pytest.raises(OSError, match="disk error"):
        apply_migration(tmp_path, plan)

    assert (tmp_path / ".claude/agents/a.md").read_bytes() == b"a"
    assert (tmp_path / ".claude/agents/b.md").read_bytes() == b"b"


def test_approved_symlink_is_removed_and_rollback_restores_it(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / ".claude/skills").mkdir(parents=True)
    (tmp_path / ".agents").mkdir()
    (tmp_path / ".agents/skills").symlink_to("../.claude/skills")
    monkeypatch.setattr(inventory, "load_known_paths", lambda: ("base", {}))
    plan = plan_migration(tmp_path)

    result = apply_migration(tmp_path, plan, approve_conflicts=[".agents/skills"])

    assert not (tmp_path / ".agents/skills").is_symlink()
    assert (tmp_path / ".claude/skills").is_dir()
    rollback_migration(tmp_path, result.snapshot_id)
    assert os.readlink(tmp_path / ".agents/skills") == "../.claude/skills"


def test_approved_generated_directory_is_removed_and_rollback_restores_files(
    tmp_path: Path, monkeypatch
) -> None:
    (tmp_path / ".opencode/plugins").mkdir(parents=True)
    (tmp_path / ".opencode/plugins/x.ts").write_bytes(b"x")
    (tmp_path / ".opencode/opencode.json").write_bytes(b"{}")
    monkeypatch.setattr(inventory, "load_known_paths", lambda: ("base", {}))
    plan = plan_migration(tmp_path)

    result = apply_migration(tmp_path, plan, approve_conflicts=[".opencode"])

    assert not (tmp_path / ".opencode").exists()
    rollback_migration(tmp_path, result.snapshot_id)
    assert (tmp_path / ".opencode/plugins/x.ts").read_bytes() == b"x"
    assert (tmp_path / ".opencode/opencode.json").read_bytes() == b"{}"


def test_rollback_restores_the_exact_pre_apply_state(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / ".claude/skills/brainstorm").mkdir(parents=True)
    (tmp_path / ".claude/skills/brainstorm/SKILL.md").write_bytes(b"v1")
    (tmp_path / ".claude/agents").mkdir()
    (tmp_path / ".claude/agents/fixer.md").write_bytes(b"edited")
    (tmp_path / ".agent-memory").mkdir()
    (tmp_path / ".agent-memory/MEMORY.md").write_bytes(b"mine")
    known = {
        ".claude/skills/brainstorm/SKILL.md": KnownPath("skill", "DELETE", _sha(b"v1")),
        ".claude/agents/fixer.md": KnownPath("agent", "REWRITE", _sha(b"orig")),
    }
    monkeypatch.setattr(inventory, "load_known_paths", lambda: ("base", known))
    before = {
        str(p.relative_to(tmp_path)): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()
    }
    plan = plan_migration(tmp_path)
    result = apply_migration(tmp_path, plan, approve_conflicts=[".claude/agents/fixer.md"])

    restored = rollback_migration(tmp_path, result.snapshot_id)

    after = {
        str(p.relative_to(tmp_path)): p.read_bytes()
        for p in tmp_path.rglob("*")
        if p.is_file() and ".harness" not in p.parts
    }
    assert {k: v for k, v in before.items() if ".harness" not in k} == after
    assert sorted(restored) == [
        ".claude/agents/fixer.md",
        ".claude/skills/brainstorm/SKILL.md",
    ]


def test_apply_rejects_approval_for_path_that_is_not_a_conflict(
    tmp_path: Path, monkeypatch
) -> None:
    (tmp_path / ".claude/agents").mkdir(parents=True)
    (tmp_path / ".claude/agents/a.md").write_bytes(b"a")
    known = {".claude/agents/a.md": KnownPath("agent", "DELETE", _sha(b"a"))}
    monkeypatch.setattr(inventory, "load_known_paths", lambda: ("base", known))
    plan = plan_migration(tmp_path)

    with pytest.raises(ValueError, match="CLAUDE.md"):
        apply_migration(tmp_path, plan, approve_conflicts=["CLAUDE.md"])

    assert (tmp_path / ".claude/agents/a.md").exists()
