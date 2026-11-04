import hashlib
import os
from pathlib import Path

from seh.contracts import (
    CanonicalSpec,
    ChangeAction,
    Diagnostic,
    DiscoveryReport,
    GeneratedPlan,
    HostId,
    PlannedChange,
    RenderContext,
    RiskRank,
    RuntimeCapabilityReport,
    SkillSpec,
)
from seh.ownership import OwnershipManifest
from seh.providers.hosts.common import MANAGED_BEGIN, MANAGED_END
from seh.sync import plan_sync

ALL_HOSTS = [HostId.CLAUDE, HostId.ANTIGRAVITY, HostId.CODEX, HostId.OPENCODE]


class FakeAdapter:
    def __init__(self, host: HostId, changes: list[PlannedChange]) -> None:
        self.id = host
        self._changes = changes

    def probe(self) -> RuntimeCapabilityReport:
        return RuntimeCapabilityReport(self.id.value, False, None, None, {}, False, ())

    def render(self, spec: CanonicalSpec, ctx: RenderContext) -> GeneratedPlan:
        return GeneratedPlan(self.id, tuple(self._changes), (), ())

    def lint(self, plan: GeneratedPlan) -> tuple[Diagnostic, ...]:
        return ()

    def discover(self, workspace: Path) -> DiscoveryReport:
        return DiscoveryReport(self.id, {}, ())


def test_shared_paths_merge_and_list_all_owners(tmp_path: Path) -> None:
    spec = CanonicalSpec("共通指示", (SkillSpec("my-skill", "説明", "本文"),), (), ())

    plan = plan_sync(tmp_path, [HostId.CODEX, HostId.OPENCODE], spec=spec)

    by_path = {item.path: item for item in plan.items}
    assert len([i for i in plan.items if i.path == "AGENTS.md"]) == 1
    assert set(by_path["AGENTS.md"].owners) == {"host:codex", "host:opencode"}
    skill_item = by_path[".agents/skills/my-skill/SKILL.md"]
    assert len(skill_item.owners) == 2
    assert skill_item.status == "NEW"
    assert plan.conflicts == ()


def test_same_path_with_different_content_is_collision(tmp_path: Path) -> None:
    spec = CanonicalSpec("x", (), (), ())
    a = FakeAdapter(
        HostId.CODEX, [PlannedChange("shared.md", ChangeAction.UPDATE, b"A\n", "r", "host:a")]
    )
    b = FakeAdapter(
        HostId.OPENCODE, [PlannedChange("shared.md", ChangeAction.UPDATE, b"B\n", "r", "host:b")]
    )

    plan = plan_sync(
        tmp_path,
        [HostId.CODEX, HostId.OPENCODE],
        spec=spec,
        adapters={HostId.CODEX: a, HostId.OPENCODE: b},
    )

    assert "PATH_CONTENT_COLLISION:shared.md" in plan.collisions
    assert [c.path for c in plan.conflicts] == ["shared.md"]
    assert plan.conflicts[0].status == "CONTENT_COLLISION"
    assert plan.items == ()


def test_claude_md_user_text_is_preserved_when_block_is_inserted(tmp_path: Path) -> None:
    (tmp_path / "CLAUDE.md").write_text("# 私のメモ\n手書き\n", encoding="utf-8")
    spec = CanonicalSpec("x", (), (), ())

    plan = plan_sync(tmp_path, [HostId.CLAUDE], spec=spec)

    item = next(i for i in plan.items if i.path == "CLAUDE.md")
    text = item.content.decode()
    assert item.status == "BLOCK_INSERT"
    assert text.startswith("# 私のメモ\n手書き\n")
    assert f"{MANAGED_BEGIN}\n@AGENTS.md\n{MANAGED_END}\n" in text


def test_block_update_replaces_only_the_block(tmp_path: Path) -> None:
    old_block = f"{MANAGED_BEGIN}\nold\n{MANAGED_END}\n"
    (tmp_path / "AGENTS.md").write_text(f"前文\n\n{old_block}\n後文\n", encoding="utf-8")
    manifest = OwnershipManifest.load(tmp_path)
    manifest.record("AGENTS.md", hashlib.sha256(old_block.encode()).hexdigest(), "g", "2.0.0")
    manifest.save(tmp_path)
    spec = CanonicalSpec("new", (), (), ())

    plan = plan_sync(tmp_path, [HostId.CODEX], spec=spec)

    item = next(i for i in plan.items if i.path == "AGENTS.md")
    assert item.status == "BLOCK_UPDATE"
    assert item.content.decode() == (f"前文\n\n{MANAGED_BEGIN}\nnew\n{MANAGED_END}\n\n後文\n")


def test_user_edit_inside_block_is_user_modified(tmp_path: Path) -> None:
    old_block = f"{MANAGED_BEGIN}\nold\n{MANAGED_END}\n"
    edited = f"{MANAGED_BEGIN}\nold + user edit\n{MANAGED_END}\n"
    (tmp_path / "AGENTS.md").write_text(edited, encoding="utf-8")
    manifest = OwnershipManifest.load(tmp_path)
    manifest.record("AGENTS.md", hashlib.sha256(old_block.encode()).hexdigest(), "g", "2.0.0")
    manifest.save(tmp_path)
    spec = CanonicalSpec("new", (), (), ())

    plan = plan_sync(tmp_path, [HostId.CODEX], spec=spec)

    assert [c.status for c in plan.conflicts] == ["USER_MODIFIED"]
    assert all(i.path != "AGENTS.md" for i in plan.items)


def test_unmanaged_existing_file_is_user_owned_with_three_way_diff(tmp_path: Path) -> None:
    skill = tmp_path / ".agents" / "skills" / "my-skill" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("手書きのスキル\n", encoding="utf-8")
    spec = CanonicalSpec("x", (SkillSpec("my-skill", "説明", "本文"),), (), ())

    plan = plan_sync(tmp_path, [HostId.CODEX], spec=spec)

    conflict = next(c for c in plan.conflicts if c.path.endswith("SKILL.md"))
    assert conflict.status == "USER_OWNED"
    assert conflict.diff is not None
    assert "user changes" in conflict.diff
    assert "手書きのスキル" in conflict.diff


def test_claude_and_opencode_skill_is_reported_as_discovery_collision(tmp_path: Path) -> None:
    spec = CanonicalSpec("x", (SkillSpec("my-skill", "説明", "本文"),), (), ())

    plan = plan_sync(tmp_path, [HostId.CLAUDE, HostId.OPENCODE], spec=spec)

    assert any("my-skill" in c and "opencode" in c for c in plan.collisions)
    assert plan.conflicts == ()


def test_single_host_has_no_discovery_collision(tmp_path: Path) -> None:
    spec = CanonicalSpec("x", (SkillSpec("my-skill", "説明", "本文"),), (), ())

    plan = plan_sync(tmp_path, [HostId.CLAUDE], spec=spec)

    assert plan.collisions == ()


def test_risk_is_assigned_from_path(tmp_path: Path) -> None:
    spec = CanonicalSpec("x", (), (), ())
    adapter = FakeAdapter(
        HostId.CLAUDE,
        [
            PlannedChange(".claude/settings.json", ChangeAction.UPDATE, b"{}\n", "r", "o"),
            PlannedChange("docs/a.md", ChangeAction.UPDATE, b"a\n", "r", "o"),
        ],
    )

    plan = plan_sync(tmp_path, [HostId.CLAUDE], spec=spec, adapters={HostId.CLAUDE: adapter})

    risks = {i.path: i.risk for i in plan.items}
    assert risks[".claude/settings.json"] == RiskRank.R2
    assert risks["docs/a.md"] == RiskRank.R0


def test_unsafe_path_is_reported_not_raised(tmp_path: Path) -> None:
    spec = CanonicalSpec("x", (), (), ())
    adapter = FakeAdapter(
        HostId.CLAUDE, [PlannedChange("../outside.md", ChangeAction.UPDATE, b"a", "r", "o")]
    )

    plan = plan_sync(tmp_path, [HostId.CLAUDE], spec=spec, adapters={HostId.CLAUDE: adapter})

    assert plan.items == ()
    assert [d.code for d in plan.diagnostics] == ["SYNC_UNSAFE_PATH"]


def test_plan_does_not_touch_the_filesystem(tmp_path: Path) -> None:
    (tmp_path / "CLAUDE.md").write_text("手書き\n", encoding="utf-8")
    spec = CanonicalSpec("x", (SkillSpec("my-skill", "説明", "本文"),), (), ())
    before = {
        p.relative_to(tmp_path).as_posix(): (p.stat().st_mtime_ns, p.stat().st_size)
        for p in tmp_path.rglob("*")
    }

    plan_sync(tmp_path, ALL_HOSTS, spec=spec)

    after = {
        p.relative_to(tmp_path).as_posix(): (p.stat().st_mtime_ns, p.stat().st_size)
        for p in tmp_path.rglob("*")
    }
    assert after == before
    assert os.listdir(tmp_path) == ["CLAUDE.md"]
