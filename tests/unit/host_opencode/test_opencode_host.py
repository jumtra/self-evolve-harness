import subprocess
from pathlib import Path

import pytest
import yaml

from seh.contracts import (
    AgentSpec,
    CanonicalSpec,
    CapabilityLevel,
    ChangeAction,
    DiagnosticLevel,
    GeneratedPlan,
    HostId,
    PlannedChange,
    RenderContext,
    RuleSpec,
    SkillSpec,
)
from seh.providers.hosts.common import MANAGED_BLOCK_REASON
from seh.providers.hosts.opencode import OpenCodeHostAdapter

OWNER = "host:opencode"


def _skill(skill_id: str = "work") -> SkillSpec:
    return SkillSpec(id=skill_id, description="作業する", body="手順")


def _agent(*, read_only: bool) -> AgentSpec:
    return AgentSpec(
        id="reviewer",
        description="レビューする",
        instructions="指示本文",
        tools=("Read",),
        read_only=read_only,
        model="opus",
    )


def _spec(
    *,
    skills: tuple[SkillSpec, ...] = (),
    agents: tuple[AgentSpec, ...] = (),
    rules: tuple[RuleSpec, ...] = (),
) -> CanonicalSpec:
    return CanonicalSpec(instructions="共通方針", skills=skills, agents=agents, rules=rules)


def _ctx(tmp_path: Path, *hosts: HostId) -> RenderContext:
    return RenderContext(
        root=tmp_path, enabled_hosts=hosts or (HostId.OPENCODE,), project_name="demo"
    )


def _plan(tmp_path: Path, spec: CanonicalSpec, *hosts: HostId) -> GeneratedPlan:
    return OpenCodeHostAdapter().render(spec, _ctx(tmp_path, *hosts))


def _by_path(plan: GeneratedPlan) -> dict[str, PlannedChange]:
    return {c.path: c for c in plan.changes}


def _frontmatter(change: PlannedChange) -> dict[str, object]:
    assert change.content is not None
    return yaml.safe_load(change.content.decode().split("---\n")[1])


def _capability(plan: GeneratedPlan, feature: str) -> CapabilityLevel:
    return next(c.level for c in plan.capabilities if c.feature == feature)


def _custom_plan(path: str, text: str) -> GeneratedPlan:
    change = PlannedChange(path, ChangeAction.UPDATE, text.encode(), "x", OWNER)
    return GeneratedPlan(HostId.OPENCODE, (change,), (), ())


def _lint_codes(plan: GeneratedPlan) -> list[str]:
    return [d.code for d in OpenCodeHostAdapter().lint(plan)]


# --- render ---


def test_render_emits_agents_md_as_managed_block(tmp_path: Path) -> None:
    changes = _by_path(_plan(tmp_path, _spec()))

    assert changes["AGENTS.md"].reason == MANAGED_BLOCK_REASON
    assert changes["AGENTS.md"].owner == OWNER


def test_render_emits_shared_skill_only_under_agents_skills(tmp_path: Path) -> None:
    changes = _by_path(_plan(tmp_path, _spec(skills=(_skill(),))))

    assert ".agents/skills/work/SKILL.md" in changes
    assert not [p for p in changes if p.startswith(".opencode/skills")]
    assert changes[".agents/skills/work/SKILL.md"].owner == OWNER


def test_render_read_only_agent_denies_edit_and_bash(tmp_path: Path) -> None:
    changes = _by_path(_plan(tmp_path, _spec(agents=(_agent(read_only=True),))))

    meta = _frontmatter(changes[".opencode/agents/reviewer.md"])
    assert meta == {
        "description": "レビューする",
        "mode": "subagent",
        "permission": {"edit": "deny", "bash": "deny"},
    }


def test_render_writable_agent_allows_edit_and_asks_bash(tmp_path: Path) -> None:
    changes = _by_path(_plan(tmp_path, _spec(agents=(_agent(read_only=False),))))

    meta = _frontmatter(changes[".opencode/agents/reviewer.md"])
    assert meta["permission"] == {"edit": "allow", "bash": "ask"}


def test_render_agent_body_has_instructions_and_no_model(tmp_path: Path) -> None:
    changes = _by_path(_plan(tmp_path, _spec(agents=(_agent(read_only=True),))))

    content = changes[".opencode/agents/reviewer.md"].content
    assert content is not None
    assert "指示本文" in content.decode()
    assert "model" not in _frontmatter(changes[".opencode/agents/reviewer.md"])


def test_render_does_not_generate_rules(tmp_path: Path) -> None:
    rule = RuleSpec(id="py", description="d", body="b", globs=("**/*.py",))

    plan = _plan(tmp_path, _spec(rules=(rule,)))

    assert [c.path for c in plan.changes] == ["AGENTS.md"]
    assert _capability(plan, "rules.path_scoped") is CapabilityLevel.UNSUPPORTED


def test_render_with_claude_enabled_warns_collision_and_adapts_skills(tmp_path: Path) -> None:
    plan = _plan(tmp_path, _spec(), HostId.CLAUDE, HostId.OPENCODE)

    codes = {d.code: d.level for d in plan.diagnostics}
    assert codes["SKILL_DISCOVERY_COLLISION"] is DiagnosticLevel.WARN
    assert _capability(plan, "skills") is CapabilityLevel.ADAPTED
    skills = next(c for c in plan.capabilities if c.feature == "skills")
    assert "COLLISION" in skills.reason


def test_render_alone_has_no_collision_and_native_capabilities(tmp_path: Path) -> None:
    plan = _plan(tmp_path, _spec())

    assert plan.diagnostics == ()
    for feature in ("instructions", "skills", "agents", "agents.read_only", "permissions"):
        assert _capability(plan, feature) is CapabilityLevel.NATIVE
    assert _capability(plan, "hooks.pre_tool_use") is CapabilityLevel.NATIVE


# --- lint ---


def test_lint_accepts_rendered_plan(tmp_path: Path) -> None:
    plan = _plan(tmp_path, _spec(skills=(_skill(),), agents=(_agent(read_only=True),)))

    assert OpenCodeHostAdapter().lint(plan) == ()


def test_lint_flags_skill_name_not_matching_directory() -> None:
    plan = _custom_plan(
        ".agents/skills/work/SKILL.md", "---\nname: other\ndescription: d\n---\n\nb\n"
    )

    assert _lint_codes(plan) == ["OPENCODE_SKILL_NAME"]


def test_lint_flags_skill_name_violating_pattern() -> None:
    plan = _custom_plan(
        ".agents/skills/Bad_Name/SKILL.md", "---\nname: Bad_Name\ndescription: d\n---\n\nb\n"
    )

    assert _lint_codes(plan) == ["OPENCODE_SKILL_NAME"]


def test_lint_flags_overlong_skill_description() -> None:
    long = "x" * 1025
    plan = _custom_plan(
        ".agents/skills/work/SKILL.md", f"---\nname: work\ndescription: {long}\n---\n\nb\n"
    )

    assert _lint_codes(plan) == ["OPENCODE_SKILL_DESCRIPTION"]


def test_lint_flags_agent_without_description() -> None:
    plan = _custom_plan(".opencode/agents/a.md", "---\nmode: subagent\n---\n\nb\n")

    assert _lint_codes(plan) == ["OPENCODE_AGENT_FIELD"]


def test_lint_flags_invalid_agent_mode() -> None:
    plan = _custom_plan(".opencode/agents/a.md", "---\ndescription: d\nmode: worker\n---\n\nb\n")

    assert _lint_codes(plan) == ["OPENCODE_AGENT_FIELD"]


def test_lint_flags_read_only_agent_whose_edit_is_not_denied(tmp_path: Path) -> None:
    plan = _plan(tmp_path, _spec(agents=(_agent(read_only=True),)))
    path = ".opencode/agents/reviewer.md"
    tampered = _by_path(plan)[path].content
    assert tampered is not None
    broken = PlannedChange(
        path,
        ChangeAction.UPDATE,
        tampered.replace(b"edit: deny", b"edit: allow"),
        "agent",
        OWNER,
    )
    bad_plan = GeneratedPlan(HostId.OPENCODE, (broken,), (), ())

    assert _lint_codes(bad_plan) == ["OPENCODE_READ_ONLY_PERMISSION"]


# --- discover ---


def _write_skill(root: Path, base: str, name: str) -> None:
    path = root / base / name / "SKILL.md"
    path.parent.mkdir(parents=True)
    path.write_text(f"---\nname: {name}\ndescription: d\n---\n")


def test_discover_reports_collision_for_same_name_in_claude_and_agents(tmp_path: Path) -> None:
    _write_skill(tmp_path, ".claude/skills", "work")
    _write_skill(tmp_path, ".agents/skills", "work")

    report = OpenCodeHostAdapter().discover(tmp_path, env={})

    assert report.collisions == ("work",)
    assert report.skills["work"] == (".claude/skills/work/SKILL.md", ".agents/skills/work/SKILL.md")


def test_discover_excludes_claude_skills_when_disable_claude_env_set(tmp_path: Path) -> None:
    _write_skill(tmp_path, ".claude/skills", "work")
    _write_skill(tmp_path, ".agents/skills", "work")

    report = OpenCodeHostAdapter().discover(
        tmp_path, env={"OPENCODE_DISABLE_CLAUDE_CODE_SKILLS": "1"}
    )

    assert report.collisions == ()
    assert report.skills["work"] == (".agents/skills/work/SKILL.md",)


def test_discover_excludes_claude_and_agents_when_external_skills_disabled(
    tmp_path: Path,
) -> None:
    _write_skill(tmp_path, ".claude/skills", "work")
    _write_skill(tmp_path, ".agents/skills", "work")
    _write_skill(tmp_path, ".opencode/skills", "own")

    report = OpenCodeHostAdapter().discover(tmp_path, env={"OPENCODE_DISABLE_EXTERNAL_SKILLS": "1"})

    assert dict(report.skills) == {"own": (".opencode/skills/own/SKILL.md",)}


def test_discover_reads_process_environment_by_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_skill(tmp_path, ".claude/skills", "work")
    _write_skill(tmp_path, ".agents/skills", "work")
    monkeypatch.setenv("OPENCODE_DISABLE_CLAUDE_CODE_SKILLS", "1")

    assert OpenCodeHostAdapter().discover(tmp_path).collisions == ()


# --- probe ---


def test_probe_without_opencode_on_path_reports_not_installed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("seh.runtime.cli_capability.shutil.which", lambda _cmd: None)

    report = OpenCodeHostAdapter().probe()

    assert report.host == "opencode"
    assert report.installed is False
    assert set(report.capabilities) == {"format", "dir", "agent"}


# --- no subprocess ---


def test_render_lint_discover_start_no_subprocess(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*_a: object, **_k: object) -> None:
        raise AssertionError("subprocess must not be started")

    monkeypatch.setattr(subprocess, "Popen", boom)
    monkeypatch.setattr(subprocess, "run", boom)
    adapter = OpenCodeHostAdapter()

    plan = adapter.render(
        _spec(skills=(_skill(),), agents=(_agent(read_only=True),)), _ctx(tmp_path)
    )
    adapter.lint(plan)
    adapter.discover(tmp_path, env={})
