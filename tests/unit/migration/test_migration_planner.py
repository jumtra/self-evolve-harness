import hashlib
from pathlib import Path

from seh.migration import inventory
from seh.migration.inventory import KnownPath
from seh.migration.planner import (
    MigrationAction,
    load_plan,
    plan_migration,
    save_plan,
)


def test_unmodified_known_files_follow_their_v2_action(tmp_path: Path, monkeypatch) -> None:
    contents = {
        ".claude/agents/ci-triage.md": (b"a", "DELETE"),
        ".claude/agents/fixer.md": (b"b", "REWRITE"),
        ".claude/_reference.md": (b"c", "MOVE"),
        ".claude/templates/t.md": (b"d", "KEEP"),
    }
    known = {}
    for rel, (body, action) in contents.items():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_bytes(body)
        known[rel] = KnownPath(
            kind="other", v2_action=action, sha256=hashlib.sha256(body).hexdigest()
        )
    monkeypatch.setattr(inventory, "load_known_paths", lambda: ("base", known))

    plan = plan_migration(tmp_path)

    assert {i.path: i.action for i in plan.items} == {
        ".claude/agents/ci-triage.md": MigrationAction.DELETE,
        ".claude/agents/fixer.md": MigrationAction.REWRITE,
        ".claude/_reference.md": MigrationAction.MOVE,
        ".claude/templates/t.md": MigrationAction.KEEP,
    }
    assert plan.baseline_ref == "base"


def test_modified_known_file_is_user_owned_conflict_with_sha_diff(
    tmp_path: Path, monkeypatch
) -> None:
    (tmp_path / ".claude/agents").mkdir(parents=True)
    (tmp_path / ".claude/agents/fixer.md").write_bytes(b"edited by user")
    baseline = hashlib.sha256(b"original").hexdigest()
    known = {".claude/agents/fixer.md": KnownPath("agent", "REWRITE", baseline)}
    monkeypatch.setattr(inventory, "load_known_paths", lambda: ("base", known))

    (item,) = plan_migration(tmp_path).items

    assert item.action is MigrationAction.USER_OWNED_CONFLICT
    assert item.baseline_sha256 == baseline
    assert item.current_sha256 == hashlib.sha256(b"edited by user").hexdigest()
    assert item.diff is not None
    assert baseline in item.diff
    assert item.current_sha256 is not None
    assert item.current_sha256 in item.diff


def test_missing_known_file_is_not_in_plan(tmp_path: Path, monkeypatch) -> None:
    known = {".claude/agents/fixer.md": KnownPath("agent", "REWRITE", "0" * 64)}
    monkeypatch.setattr(inventory, "load_known_paths", lambda: ("base", known))

    assert plan_migration(tmp_path).items == ()


def test_symlinked_generated_target_is_conflict_naming_link_target(
    tmp_path: Path, monkeypatch
) -> None:
    (tmp_path / ".claude/skills").mkdir(parents=True)
    (tmp_path / ".agents").mkdir()
    (tmp_path / ".agents/skills").symlink_to("../.claude/skills")
    monkeypatch.setattr(inventory, "load_known_paths", lambda: ("base", {}))

    (item,) = plan_migration(tmp_path).items

    assert item.path == ".agents/skills"
    assert item.action is MigrationAction.USER_OWNED_CONFLICT
    assert "../.claude/skills" in item.reason


def test_existing_generated_targets_are_conflicts_but_skills_json_is_keep(
    tmp_path: Path, monkeypatch
) -> None:
    (tmp_path / ".agents").mkdir()
    (tmp_path / ".agents/rules").mkdir()
    (tmp_path / ".agents/rules/r.md").write_text("mine")
    (tmp_path / ".agents/hooks.json").write_text("{}")
    (tmp_path / ".agents/skills.json").write_text("{}")
    (tmp_path / ".codex").mkdir()
    (tmp_path / ".codex/config.toml").write_text("x")
    monkeypatch.setattr(inventory, "load_known_paths", lambda: ("base", {}))

    plan = plan_migration(tmp_path)

    assert {i.path: i.action for i in plan.items} == {
        ".agents/hooks.json": MigrationAction.USER_OWNED_CONFLICT,
        ".agents/rules": MigrationAction.USER_OWNED_CONFLICT,
        ".agents/skills.json": MigrationAction.KEEP,
        ".codex": MigrationAction.USER_OWNED_CONFLICT,
    }


def test_user_data_is_always_keep_even_when_modified(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / ".agent-memory").mkdir()
    (tmp_path / ".agent-memory/MEMORY.md").write_text("my notes")
    (tmp_path / ".agent-memory/extra.md").write_text("more")
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude/settings.local.json").write_text("{}")
    known = {".agent-memory/MEMORY.md": KnownPath("memory", "KEEP", "0" * 64)}
    monkeypatch.setattr(inventory, "load_known_paths", lambda: ("base", known))

    plan = plan_migration(tmp_path)

    assert {i.path: i.action for i in plan.items} == {
        ".agent-memory/MEMORY.md": MigrationAction.KEEP,
        ".claude/settings.local.json": MigrationAction.KEEP,
    }


def test_user_skill_outside_v1_list_is_not_planned_for_removal(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / ".claude/skills/mine").mkdir(parents=True)
    (tmp_path / ".claude/skills/mine/SKILL.md").write_text("mine")
    (tmp_path / ".claude/skills/brainstorm").mkdir()
    (tmp_path / ".claude/skills/brainstorm/SKILL.md").write_text("same name, own content")
    known = {
        ".claude/skills/brainstorm/SKILL.md": KnownPath("skill", "DELETE", "0" * 64),
    }
    monkeypatch.setattr(inventory, "load_known_paths", lambda: ("base", known))

    plan = plan_migration(tmp_path)

    assert {i.path: i.action for i in plan.items} == {
        ".claude/skills/brainstorm/SKILL.md": MigrationAction.USER_OWNED_CONFLICT,
    }


def test_plan_is_read_only(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / ".claude/agents").mkdir(parents=True)
    (tmp_path / ".claude/agents/fixer.md").write_bytes(b"x")
    (tmp_path / ".agents").mkdir()
    (tmp_path / ".agents/skills").symlink_to("../.claude")
    known = {
        ".claude/agents/fixer.md": KnownPath("agent", "REWRITE", hashlib.sha256(b"x").hexdigest())
    }
    monkeypatch.setattr(inventory, "load_known_paths", lambda: ("base", known))
    before = {
        str(p): p.is_symlink() or p.read_bytes() for p in tmp_path.rglob("*") if not p.is_dir()
    }

    plan_migration(tmp_path)

    after = {
        str(p): p.is_symlink() or p.read_bytes() for p in tmp_path.rglob("*") if not p.is_dir()
    }
    assert after == before


def test_save_and_load_plan_round_trip(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / ".claude/agents").mkdir(parents=True)
    (tmp_path / ".claude/agents/fixer.md").write_bytes(b"x")
    known = {
        ".claude/agents/fixer.md": KnownPath("agent", "REWRITE", hashlib.sha256(b"x").hexdigest())
    }
    monkeypatch.setattr(inventory, "load_known_paths", lambda: ("base", known))
    plan = plan_migration(tmp_path)

    saved = save_plan(tmp_path, plan)

    assert saved == tmp_path / ".harness/state" / f"migrate-plan-{plan.plan_id}.json"
    assert load_plan(saved) == plan
