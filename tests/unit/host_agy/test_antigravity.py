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
from seh.providers.hosts import antigravity as agy_module
from seh.providers.hosts.antigravity import AntigravityHostAdapter
from seh.providers.hosts.common import MANAGED_BLOCK_REASON

OWNER = "host:antigravity"


def _spec(
    *,
    skills: tuple[SkillSpec, ...] = (),
    agents: tuple[AgentSpec, ...] = (),
    rules: tuple[RuleSpec, ...] = (),
) -> CanonicalSpec:
    return CanonicalSpec(instructions="共通方針", skills=skills, agents=agents, rules=rules)


def _ctx(tmp_path: Path) -> RenderContext:
    return RenderContext(root=tmp_path, enabled_hosts=(HostId.ANTIGRAVITY,), project_name="demo")


def _render(tmp_path: Path, spec: CanonicalSpec) -> dict[str, PlannedChange]:
    plan = AntigravityHostAdapter().render(spec, _ctx(tmp_path))
    return {c.path: c for c in plan.changes}


def _frontmatter(change: PlannedChange) -> dict[str, object]:
    assert change.content is not None
    text = change.content.decode()
    return yaml.safe_load(text.split("---\n")[1])


def _plan(*changes: PlannedChange) -> GeneratedPlan:
    return GeneratedPlan(host=HostId.ANTIGRAVITY, changes=changes, diagnostics=(), capabilities=())


def _file(path: str, text: str) -> PlannedChange:
    return PlannedChange(path, ChangeAction.UPDATE, text.encode(), "test", OWNER)


def _codes(plan: GeneratedPlan) -> list[tuple[DiagnosticLevel, str]]:
    return [(d.level, d.code) for d in AntigravityHostAdapter().lint(plan)]


# --- render ---


def test_adapter_id_is_antigravity() -> None:
    assert AntigravityHostAdapter().id == HostId.ANTIGRAVITY


def test_render_writes_agents_md_managed_block_and_no_gemini_md(tmp_path: Path) -> None:
    changes = _render(tmp_path, _spec())

    assert changes["AGENTS.md"].reason == MANAGED_BLOCK_REASON
    assert changes["AGENTS.md"].owner == OWNER
    assert "GEMINI.md" not in changes


def test_render_skill_uses_shared_dir_without_claude_keys(tmp_path: Path) -> None:
    skill = SkillSpec(
        id="work",
        description="開発依頼を処理する",
        body="手順",
        claude_frontmatter={"allowed-tools": "Bash"},
    )

    changes = _render(tmp_path, _spec(skills=(skill,)))

    assert _frontmatter(changes[".agents/skills/work/SKILL.md"]) == {
        "name": "work",
        "description": "開発依頼を処理する",
    }


def test_render_always_rule_uses_always_on_trigger(tmp_path: Path) -> None:
    rule = RuleSpec(id="style", description="書式", body="本文", always=True)

    changes = _render(tmp_path, _spec(rules=(rule,)))

    assert _frontmatter(changes[".agents/rules/style.md"]) == {"trigger": "always_on"}


def test_render_glob_rule_joins_globs_with_comma(tmp_path: Path) -> None:
    rule = RuleSpec(id="py", description="Python", body="本文", globs=("src/**/*.py", "tests/*.py"))

    changes = _render(tmp_path, _spec(rules=(rule,)))

    assert _frontmatter(changes[".agents/rules/py.md"]) == {
        "trigger": "glob",
        "globs": "src/**/*.py,tests/*.py",
    }


def test_render_rule_without_globs_or_always_uses_model_decision(tmp_path: Path) -> None:
    rule = RuleSpec(id="misc", description="関連時に読む", body="本文")

    changes = _render(tmp_path, _spec(rules=(rule,)))

    assert _frontmatter(changes[".agents/rules/misc.md"]) == {
        "trigger": "model_decision",
        "description": "関連時に読む",
    }


def test_render_read_only_agent_turns_command_execution_off_and_omits_tools(
    tmp_path: Path,
) -> None:
    agent = AgentSpec(
        id="reviewer",
        description="レビュー担当",
        instructions="差分を確認する",
        tools=("Read", "Grep"),
        read_only=True,
    )

    change = _render(tmp_path, _spec(agents=(agent,)))[".agents/agents/reviewer.md"]

    assert _frontmatter(change) == {
        "name": "reviewer",
        "description": "レビュー担当",
        "commandExecutionPolicy": "off",
    }
    assert change.content is not None
    body = change.content.decode()
    assert "差分を確認する" in body
    assert body.rstrip().endswith("ファイルを編集しないこと（読み取り専用）")


def test_render_writable_agent_has_no_command_policy_and_no_read_only_note(
    tmp_path: Path,
) -> None:
    agent = AgentSpec(
        id="builder",
        description="実装担当",
        instructions="実装する",
        tools=("Edit",),
        read_only=False,
    )

    change = _render(tmp_path, _spec(agents=(agent,)))[".agents/agents/builder.md"]

    assert _frontmatter(change) == {"name": "builder", "description": "実装担当"}
    assert change.content is not None
    assert "読み取り専用" not in change.content.decode()


def test_render_changes_are_all_owned_by_antigravity(tmp_path: Path) -> None:
    rule = RuleSpec(id="style", description="書式", body="本文", always=True)

    changes = _render(tmp_path, _spec(rules=(rule,)))

    assert {c.owner for c in changes.values()} == {OWNER}


def test_render_capabilities_report_managed_runtime_as_policy_blocked(tmp_path: Path) -> None:
    plan = AntigravityHostAdapter().render(_spec(), _ctx(tmp_path))

    caps = {c.feature: c for c in plan.capabilities}

    assert caps["runtime.managed"].level == CapabilityLevel.UNSUPPORTED
    assert "POLICY_BLOCKED" in caps["runtime.managed"].reason
    assert {k: v.level for k, v in caps.items() if k != "runtime.managed"} == {
        "instructions": CapabilityLevel.NATIVE,
        "skills": CapabilityLevel.NATIVE,
        "agents": CapabilityLevel.UNVERIFIED,
        "agents.read_only": CapabilityLevel.UNVERIFIED,
        "rules.path_scoped": CapabilityLevel.NATIVE,
        "hooks.pre_tool_use": CapabilityLevel.ADAPTED,
        "permissions": CapabilityLevel.UNSUPPORTED,
    }


# --- lint ---


def test_lint_accepts_rendered_plan(tmp_path: Path) -> None:
    spec = _spec(
        skills=(SkillSpec(id="work", description="d", body="b"),),
        agents=(AgentSpec("a", "d", "i", ("Read",), True),),
        rules=(
            RuleSpec(id="r1", description="d", body="b", always=True),
            RuleSpec(id="r2", description="d", body="b", globs=("*.py",)),
            RuleSpec(id="r3", description="d", body="b"),
        ),
    )
    plan = AntigravityHostAdapter().render(spec, _ctx(tmp_path))

    assert AntigravityHostAdapter().lint(plan) == ()


@pytest.mark.parametrize(
    "text",
    ["本文のみ\n", "---\ntrigger: sometimes\n---\n\n本文\n", "---\nfoo: bar\n---\n\n本文\n"],
)
def test_lint_flags_missing_or_invalid_trigger(text: str) -> None:
    plan = _plan(_file(".agents/rules/x.md", text))

    assert _codes(plan) == [(DiagnosticLevel.ERROR, "AGY_RULE_TRIGGER")]


def test_lint_flags_glob_trigger_without_globs() -> None:
    plan = _plan(_file(".agents/rules/x.md", "---\ntrigger: glob\n---\n\n本文\n"))

    assert _codes(plan) == [(DiagnosticLevel.ERROR, "AGY_RULE_TRIGGER")]


def test_lint_flags_model_decision_without_description() -> None:
    plan = _plan(_file(".agents/rules/x.md", "---\ntrigger: model_decision\n---\n\n本文\n"))

    assert _codes(plan) == [(DiagnosticLevel.ERROR, "AGY_RULE_TRIGGER")]


def test_lint_flags_rule_over_24000_bytes() -> None:
    big = "---\ntrigger: always_on\n---\n\n" + "a" * 24_000
    plan = _plan(_file(".agents/rules/x.md", big))

    assert _codes(plan) == [(DiagnosticLevel.ERROR, "AGY_RULE_TOO_LARGE")]


def test_lint_flags_skill_frontmatter_with_extra_key() -> None:
    text = "---\nname: work\ndescription: d\nallowed-tools: Bash\n---\n\n本文\n"
    plan = _plan(_file(".agents/skills/work/SKILL.md", text))

    assert _codes(plan) == [(DiagnosticLevel.ERROR, "SHARED_SKILL_EXTRA_KEY")]


@pytest.mark.parametrize("missing", ["name", "description"])
def test_lint_flags_agent_missing_required_key(missing: str) -> None:
    meta = {"name": "a", "description": "d"}
    del meta[missing]
    header = yaml.safe_dump(meta)
    plan = _plan(_file(".agents/agents/a.md", f"---\n{header}---\n\n本文\n"))

    assert _codes(plan) == [(DiagnosticLevel.ERROR, "AGY_AGENT_FIELD")]


# --- discover ---


def _skill(root: Path, base: str, name: str) -> str:
    path = root / base / name / "SKILL.md"
    path.parent.mkdir(parents=True)
    path.write_text("---\nname: x\ndescription: d\n---\n")
    return path.relative_to(root).as_posix()


def test_discover_finds_skills_in_current_and_legacy_dirs(tmp_path: Path) -> None:
    new = _skill(tmp_path, ".agents/skills", "work")
    legacy = _skill(tmp_path, ".agent/skills", "old")

    report = AntigravityHostAdapter().discover(tmp_path)

    assert report.host == HostId.ANTIGRAVITY
    assert dict(report.skills) == {"work": (new,), "old": (legacy,)}
    assert report.collisions == ()


def test_discover_reports_collision_when_same_name_in_both_dirs(tmp_path: Path) -> None:
    new = _skill(tmp_path, ".agents/skills", "work")
    legacy = _skill(tmp_path, ".agent/skills", "work")

    report = AntigravityHostAdapter().discover(tmp_path)

    assert dict(report.skills) == {"work": (new, legacy)}
    assert report.collisions == ("work",)


def test_discover_on_empty_workspace_returns_nothing(tmp_path: Path) -> None:
    report = AntigravityHostAdapter().discover(tmp_path)

    assert dict(report.skills) == {}
    assert report.collisions == ()


# --- probe ---


def test_probe_without_agy_on_path_reports_not_installed_and_policy_blocked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("seh.runtime.cli_capability.shutil.which", lambda _cmd: None)

    report = AntigravityHostAdapter().probe()

    assert report.host == "antigravity"
    assert report.installed is False
    assert report.policy_blocked is True


def test_probe_forces_policy_blocked_even_if_probe_helper_returns_false(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real = agy_module.probe_cli
    monkeypatch.setattr(
        agy_module,
        "probe_cli",
        lambda host, spec, policy_blocked=False: real(host, spec, policy_blocked=False),
    )
    monkeypatch.setattr("seh.runtime.cli_capability.shutil.which", lambda _cmd: None)

    assert AntigravityHostAdapter().probe().policy_blocked is True


# --- no subprocess ---


def test_render_lint_discover_do_not_spawn_processes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*_a: object, **_k: object) -> None:
        raise AssertionError("subprocess must not be started")

    monkeypatch.setattr(subprocess, "Popen", boom)
    monkeypatch.setattr(subprocess, "run", boom)
    adapter = AntigravityHostAdapter()

    plan = adapter.render(_spec(rules=(RuleSpec("r", "d", "b", always=True),)), _ctx(tmp_path))
    adapter.lint(plan)
    adapter.discover(tmp_path)
