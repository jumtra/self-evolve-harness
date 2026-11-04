import json
from pathlib import Path

import pytest

from seh.contracts import CanonicalSpec, HostId, SkillSpec
from seh.ownership import OwnershipManifest, Transaction
from seh.sync import SyncError, apply_sync, plan_sync

ALL_HOSTS = [HostId.CLAUDE, HostId.ANTIGRAVITY, HostId.CODEX, HostId.OPENCODE]


def test_apply_writes_files_ownership_and_lock(tmp_path: Path) -> None:
    spec = CanonicalSpec("共通指示", (SkillSpec("my-skill", "説明", "本文"),), (), ())
    plan = plan_sync(tmp_path, [HostId.CLAUDE, HostId.CODEX], spec=spec)

    written = apply_sync(
        tmp_path,
        plan,
        seh_version="2.0.0",
        cli_versions={"claude": "2.1.318", "codex": None},
    )

    assert "AGENTS.md" in written
    assert (tmp_path / ".claude/skills/my-skill/SKILL.md").is_file()
    assert (tmp_path / ".agents/skills/my-skill/SKILL.md").is_file()
    manifest = OwnershipManifest.load(tmp_path)
    assert manifest.get("AGENTS.md") is not None
    lock_text = (tmp_path / ".harness/generated.lock.json").read_text(encoding="utf-8")
    lock = json.loads(lock_text)
    assert lock["schema_version"] == 1
    assert lock["seh_version"] == "2.0.0"
    assert lock["hosts"] == {
        "claude": {"cli": "claude", "version": "2.1.318"},
        "codex": {"cli": "codex", "version": None},
    }
    assert lock["files"] == len(plan.items)
    assert str(tmp_path) not in lock_text


def test_second_plan_is_all_unchanged(tmp_path: Path) -> None:
    (tmp_path / "CLAUDE.md").write_text("# 手書き\n", encoding="utf-8")
    spec = CanonicalSpec("共通指示", (SkillSpec("my-skill", "説明", "本文"),), (), ())
    first = plan_sync(tmp_path, ALL_HOSTS, spec=spec)
    apply_sync(tmp_path, first, seh_version="2.0.0", cli_versions={})

    second = plan_sync(tmp_path, ALL_HOSTS, spec=spec)

    assert second.items
    assert {i.status for i in second.items} == {"UNCHANGED"}
    assert second.conflicts == ()
    assert (tmp_path / "CLAUDE.md").read_text(encoding="utf-8").startswith("# 手書き\n")


def test_changed_spec_updates_only_managed_block(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_text("# 前文\n", encoding="utf-8")
    first = plan_sync(tmp_path, [HostId.CODEX], spec=CanonicalSpec("v1", (), (), ()))
    apply_sync(tmp_path, first, seh_version="2.0.0", cli_versions={})
    with (tmp_path / "AGENTS.md").open("a", encoding="utf-8") as f:
        f.write("\n# 後から手書き\n")

    second = plan_sync(tmp_path, [HostId.CODEX], spec=CanonicalSpec("v2", (), (), ()))
    apply_sync(tmp_path, second, seh_version="2.0.0", cli_versions={})

    text = (tmp_path / "AGENTS.md").read_text(encoding="utf-8")
    assert "v2" in text
    assert "v1" not in text
    assert text.startswith("# 前文\n")
    assert text.endswith("# 後から手書き\n")


def test_overwrite_replaces_only_listed_conflicts(tmp_path: Path) -> None:
    skill = tmp_path / ".agents/skills/my-skill/SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("手書き\n", encoding="utf-8")
    ref = tmp_path / ".agents/skills/my-skill/references/a.md"
    ref.parent.mkdir(parents=True)
    ref.write_text("手書き参照\n", encoding="utf-8")
    spec = CanonicalSpec(
        "x", (SkillSpec("my-skill", "説明", "本文", references={"references/a.md": "新"}),), (), ()
    )
    plan = plan_sync(tmp_path, [HostId.CODEX], spec=spec)

    apply_sync(
        tmp_path,
        plan,
        overwrite=[".agents/skills/my-skill/SKILL.md"],
        seh_version="2.0.0",
        cli_versions={},
    )

    assert "本文" in skill.read_text(encoding="utf-8")
    assert ref.read_text(encoding="utf-8") == "手書き参照\n"


def test_overwrite_of_unlisted_path_is_rejected(tmp_path: Path) -> None:
    plan = plan_sync(tmp_path, [HostId.CODEX], spec=CanonicalSpec("x", (), (), ()))

    with pytest.raises(SyncError):
        apply_sync(tmp_path, plan, overwrite=["nope.md"], seh_version="2.0.0", cli_versions={})


def test_failure_midway_rolls_everything_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "CLAUDE.md").write_text("# 手書き\n", encoding="utf-8")
    spec = CanonicalSpec("x", (SkillSpec("my-skill", "説明", "本文"),), (), ())
    plan = plan_sync(tmp_path, [HostId.CLAUDE], spec=spec)
    original = Transaction.write
    calls: list[str] = []

    def failing_write(self: Transaction, path: str, data: bytes) -> None:
        calls.append(path)
        if len(calls) == 3:
            raise OSError("disk full")
        original(self, path, data)

    monkeypatch.setattr(Transaction, "write", failing_write)

    with pytest.raises(OSError, match="disk full"):
        apply_sync(tmp_path, plan, seh_version="2.0.0", cli_versions={})

    assert len(calls) == 3
    assert (tmp_path / "CLAUDE.md").read_text(encoding="utf-8") == "# 手書き\n"
    assert not (tmp_path / "AGENTS.md").exists()
    assert not (tmp_path / ".claude").exists()
    assert not (tmp_path / ".harness/ownership.json").exists()
    assert not (tmp_path / ".harness/generated.lock.json").exists()
