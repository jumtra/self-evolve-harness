import json
import os
from pathlib import Path

import pytest

from seh.contracts import HostId
from seh.init import apply as apply_module
from seh.init.apply import apply_init
from seh.init.planner import InitError, InitOptions, plan_init
from seh.migration import inventory
from seh.migration.inventory import KnownPath
from seh.ownership import OwnershipManifest
from seh.spec_loader import load_spec
from seh.sync import SyncPlan, plan_sync


def test_apply_writes_everything_and_second_sync_is_unchanged(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    spec = tmp_path / "spec"
    repo.mkdir()
    (repo / ".gitignore").write_text("*.pyc\n", encoding="utf-8")
    (spec / "instructions").mkdir(parents=True)
    (spec / "skills" / "demo").mkdir(parents=True)
    (spec / "instructions" / "core.md").write_text("# {{project_name}}\n", encoding="utf-8")
    (spec / "skills" / "demo" / "SKILL.md").write_text(
        "---\ndescription: 説明\n---\n本文\n", encoding="utf-8"
    )
    plan = plan_init(repo, InitOptions(hosts=(HostId.CLAUDE, HostId.CODEX), spec_source=spec))

    result = apply_init(repo, plan, seh_version="2.0.0", cli_versions={"claude": "1.0.0"})

    assert result.rolled_back is False
    assert result.migration_snapshot is None
    assert (repo / ".harness/config.toml").read_text(encoding="utf-8") == plan.config_toml
    assert (repo / ".harness/spec/instructions/core.md").read_text(encoding="utf-8") == "# repo\n"
    assert (repo / ".claude/skills/demo/SKILL.md").is_file()
    assert (repo / "AGENTS.md").is_file()
    assert OwnershipManifest.load(repo).get(".claude/skills/demo/SKILL.md") is not None
    lock = json.loads((repo / ".harness/generated.lock.json").read_text(encoding="utf-8"))
    assert lock["seh_version"] == "2.0.0"
    gitignore = (repo / ".gitignore").read_text(encoding="utf-8")
    assert gitignore == "*.pyc\n" + plan.gitignore_block
    again = plan_sync(
        repo, [HostId.CLAUDE, HostId.CODEX], spec=load_spec(repo / ".harness" / "spec")
    )
    assert again.items
    assert {i.status for i in again.items} == {"UNCHANGED"}
    assert again.conflicts == ()


def test_existing_gitignore_block_is_replaced_not_duplicated(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    spec = tmp_path / "spec"
    repo.mkdir()
    (repo / ".gitignore").write_text("a\n# seh:begin\n.old/\n# seh:end\nb\n", encoding="utf-8")
    (spec / "instructions").mkdir(parents=True)
    (spec / "instructions" / "core.md").write_text("x\n", encoding="utf-8")
    plan = plan_init(repo, InitOptions(spec_source=spec))

    apply_init(repo, plan, seh_version="2.0.0", cli_versions={})

    assert (repo / ".gitignore").read_text(encoding="utf-8") == f"a\n{plan.gitignore_block}b\n"


def test_v1_files_are_removed_and_modified_ones_kept_without_approval(
    tmp_path: Path, monkeypatch
) -> None:
    repo = tmp_path / "repo"
    spec = tmp_path / "spec"
    clean = repo / ".claude/skills/old-clean/SKILL.md"
    edited = repo / ".claude/skills/old-edited/SKILL.md"
    clean.parent.mkdir(parents=True)
    edited.parent.mkdir(parents=True)
    clean.write_text("v1 そのまま\n", encoding="utf-8")
    edited.write_text("ユーザーが改変\n", encoding="utf-8")
    (spec / "instructions").mkdir(parents=True)
    (spec / "skills" / "demo").mkdir(parents=True)
    (spec / "instructions" / "core.md").write_text("x\n", encoding="utf-8")
    (spec / "skills" / "demo" / "SKILL.md").write_text(
        "---\ndescription: 説明\n---\n本文\n", encoding="utf-8"
    )
    clean_digest = inventory.fingerprint(repo, ".claude/skills/old-clean/SKILL.md")
    assert clean_digest is not None
    known = {
        ".claude/skills/old-clean/SKILL.md": KnownPath("skill", "DELETE", clean_digest),
        ".claude/skills/old-edited/SKILL.md": KnownPath("skill", "DELETE", "0" * 64),
    }
    monkeypatch.setattr(inventory, "load_known_paths", lambda: ("base", known))
    plan = plan_init(repo, InitOptions(spec_source=spec))

    result = apply_init(repo, plan, seh_version="2.0.0", cli_versions={})

    assert not clean.exists()
    assert edited.read_text(encoding="utf-8") == "ユーザーが改変\n"
    assert result.migration_snapshot is not None
    assert (repo / ".claude/skills/demo/SKILL.md").is_file()


def test_approved_conflict_is_replaced(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    spec = tmp_path / "spec"
    edited = repo / ".claude/skills/old-edited/SKILL.md"
    edited.parent.mkdir(parents=True)
    edited.write_text("ユーザーが改変\n", encoding="utf-8")
    (spec / "instructions").mkdir(parents=True)
    (spec / "instructions" / "core.md").write_text("x\n", encoding="utf-8")
    known = {".claude/skills/old-edited/SKILL.md": KnownPath("skill", "DELETE", "0" * 64)}
    monkeypatch.setattr(inventory, "load_known_paths", lambda: ("base", known))
    plan = plan_init(repo, InitOptions(spec_source=spec))

    apply_init(
        repo,
        plan,
        approve_conflicts=[".claude/skills/old-edited/SKILL.md"],
        seh_version="2.0.0",
        cli_versions={},
    )

    assert not edited.exists()


def test_unknown_approval_is_rejected_before_any_write(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    spec = tmp_path / "spec"
    repo.mkdir()
    (spec / "instructions").mkdir(parents=True)
    (spec / "instructions" / "core.md").write_text("x\n", encoding="utf-8")
    plan = plan_init(repo, InitOptions(spec_source=spec))

    with pytest.raises(InitError, match="承認対象"):
        apply_init(repo, plan, approve_conflicts=["nope.md"], seh_version="2.0.0", cli_versions={})

    assert not (repo / ".harness").exists()


def test_sync_failure_rolls_back_config_spec_and_migration(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    spec = tmp_path / "spec"
    clean = repo / ".claude/skills/old-clean/SKILL.md"
    clean.parent.mkdir(parents=True)
    clean.write_text("v1 そのまま\n", encoding="utf-8")
    (repo / ".gitignore").write_text("*.pyc\n", encoding="utf-8")
    (spec / "instructions").mkdir(parents=True)
    (spec / "instructions" / "core.md").write_text("x\n", encoding="utf-8")
    digest = inventory.fingerprint(repo, ".claude/skills/old-clean/SKILL.md")
    assert digest is not None
    known = {".claude/skills/old-clean/SKILL.md": KnownPath("skill", "DELETE", digest)}
    monkeypatch.setattr(inventory, "load_known_paths", lambda: ("base", known))
    plan = plan_init(repo, InitOptions(spec_source=spec))

    def boom(*args, **kwargs):
        raise RuntimeError("sync が失敗")

    monkeypatch.setattr(apply_module, "apply_sync", boom)

    with pytest.raises(RuntimeError, match="sync が失敗") as caught:
        apply_init(repo, plan, seh_version="2.0.0", cli_versions={})

    assert "ロールバック" in "".join(caught.value.__notes__)
    assert clean.read_text(encoding="utf-8") == "v1 そのまま\n"
    assert (repo / ".gitignore").read_text(encoding="utf-8") == "*.pyc\n"
    remaining = sorted(
        str(Path(c, f).relative_to(repo))
        for c, _, files in os.walk(repo)
        for f in files
        if ".harness/backups" not in c
    )
    assert remaining == [".claude/skills/old-clean/SKILL.md", ".gitignore"]
    assert not (repo / ".harness/config.toml").exists()
    assert not (repo / ".harness/spec").exists()


def test_late_sync_failure_after_committed_write_is_rolled_back(
    tmp_path: Path, monkeypatch
) -> None:
    repo = tmp_path / "repo"
    spec = tmp_path / "spec"
    repo.mkdir()
    (spec / "instructions").mkdir(parents=True)
    (spec / "instructions" / "core.md").write_text("x\n", encoding="utf-8")
    plan = plan_init(repo, InitOptions(spec_source=spec))
    real_apply_sync = apply_module.apply_sync

    def write_then_fail(*args, **kwargs):
        real_apply_sync(*args, **kwargs)
        raise RuntimeError("lock 書込後に失敗")

    monkeypatch.setattr(apply_module, "apply_sync", write_then_fail)

    with pytest.raises(RuntimeError, match="lock 書込後に失敗"):
        apply_init(repo, plan, seh_version="2.0.0", cli_versions={})

    leftovers = sorted(
        str(Path(c, f).relative_to(repo))
        for c, _, files in os.walk(repo)
        for f in files
        if ".harness/backups" not in c
    )
    assert leftovers == []


def test_changed_sync_paths_after_migration_abort_and_roll_back(
    tmp_path: Path, monkeypatch
) -> None:
    repo = tmp_path / "repo"
    spec = tmp_path / "spec"
    repo.mkdir()
    (spec / "instructions").mkdir(parents=True)
    (spec / "instructions" / "core.md").write_text("x\n", encoding="utf-8")
    plan = plan_init(repo, InitOptions(spec_source=spec))
    called: list[str] = []

    def empty_replan(*args, **kwargs):
        called.append("replan")
        return SyncPlan(items=(), conflicts=(), collisions=(), diagnostics=())

    monkeypatch.setattr(apply_module, "plan_sync", empty_replan)
    monkeypatch.setattr(apply_module, "apply_sync", lambda *a, **k: called.append("apply"))

    with pytest.raises(InitError, match="計画と状態が食い違いました。再度 --plan してください"):
        apply_init(repo, plan, seh_version="2.0.0", cli_versions={})

    assert called == ["replan"]
    assert not (repo / ".harness/config.toml").exists()
