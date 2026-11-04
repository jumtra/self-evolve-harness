import shutil
import tomllib
from pathlib import Path

import pytest
import yaml

import seh
from seh.authoring.lint import lint_generated, lint_spec
from seh.contracts import (
    AgentSpec,
    CanonicalSpec,
    DiagnosticLevel,
    GeneratedPlan,
    HostAdapter,
    HostId,
    RenderContext,
)
from seh.providers.hosts.antigravity import AntigravityHostAdapter
from seh.providers.hosts.claude import ClaudeHostAdapter
from seh.providers.hosts.codex import CodexHostAdapter
from seh.providers.hosts.opencode import OpenCodeHostAdapter
from seh.spec_loader import load_spec

TEMPLATE_AGENTS = Path(seh.__file__).parent / "templates" / "spec" / "agents"
AGENT_IDS = ("implementer", "reviewer", "fixer", "evolver")
ADAPTERS: dict[HostId, HostAdapter] = {
    HostId.CLAUDE: ClaudeHostAdapter(),
    HostId.ANTIGRAVITY: AntigravityHostAdapter(),
    HostId.CODEX: CodexHostAdapter(),
    HostId.OPENCODE: OpenCodeHostAdapter(),
}
DESCRIPTION_LIMIT = 120
INSTRUCTIONS_LIMIT = 1_500
WRITE_TOOLS = {"Edit", "Write"}


@pytest.fixture
def spec(tmp_path: Path) -> CanonicalSpec:
    spec_dir = tmp_path / "spec"
    (spec_dir / "instructions").mkdir(parents=True)
    (spec_dir / "instructions" / "core.md").write_text("共通方針\n", encoding="utf-8")
    shutil.copytree(TEMPLATE_AGENTS, spec_dir / "agents")
    return load_spec(spec_dir)


def agent_of(spec: CanonicalSpec, agent_id: str) -> AgentSpec:
    return next(a for a in spec.agents if a.id == agent_id)


def render(spec: CanonicalSpec, host: HostId, tmp_path: Path) -> GeneratedPlan:
    ctx = RenderContext(root=tmp_path, enabled_hosts=(host,), project_name="demo")
    return ADAPTERS[host].render(spec, ctx)


def content_of(plan: GeneratedPlan, filename: str) -> str:
    change = next(c for c in plan.changes if c.path.endswith(f"/{filename}"))
    assert change.content is not None
    return change.content.decode()


def test_loads_exactly_the_four_agents(spec: CanonicalSpec) -> None:
    assert sorted(a.id for a in spec.agents) == sorted(AGENT_IDS)


def test_lint_spec_reports_no_agent_error(spec: CanonicalSpec) -> None:
    errors = [d for d in lint_spec(spec) if d.level == DiagnosticLevel.ERROR]

    assert errors == []


def test_reviewer_is_read_only(spec: CanonicalSpec) -> None:
    reviewer = agent_of(spec, "reviewer")

    assert reviewer.read_only is True
    assert reviewer.tools == ("Read", "Grep", "Glob")


def test_evolver_has_no_edit_or_write_tool(spec: CanonicalSpec) -> None:
    assert WRITE_TOOLS.isdisjoint(agent_of(spec, "evolver").tools)


@pytest.mark.parametrize("agent_id", ["implementer", "fixer"])
def test_implementer_and_fixer_can_write(spec: CanonicalSpec, agent_id: str) -> None:
    agent = agent_of(spec, agent_id)

    assert agent.read_only is False
    assert set(agent.tools) >= WRITE_TOOLS


def test_models_and_effort_follow_role(spec: CanonicalSpec) -> None:
    models = {a.id: (a.model, a.effort) for a in spec.agents}

    assert models == {
        "implementer": ("sonnet", None),
        "reviewer": ("sonnet", None),
        "fixer": ("opus", "high"),
        "evolver": ("sonnet", None),
    }


@pytest.mark.parametrize("agent_id", AGENT_IDS)
def test_description_stays_short(spec: CanonicalSpec, agent_id: str) -> None:
    assert 0 < len(agent_of(spec, agent_id).description) <= DESCRIPTION_LIMIT


@pytest.mark.parametrize("agent_id", AGENT_IDS)
def test_instructions_stay_short(spec: CanonicalSpec, agent_id: str) -> None:
    assert 0 < len(agent_of(spec, agent_id).instructions) <= INSTRUCTIONS_LIMIT


@pytest.mark.parametrize("agent_id", AGENT_IDS)
def test_instructions_have_no_template_variables(spec: CanonicalSpec, agent_id: str) -> None:
    assert "{{" not in agent_of(spec, agent_id).instructions


def test_implementer_never_commits_or_runs_full_ci(spec: CanonicalSpec) -> None:
    text = agent_of(spec, "implementer").instructions

    assert "コミット" in text
    assert "全体 CI" in text
    assert "スコープテスト" in text


def test_reviewer_takes_review_type(spec: CanonicalSpec) -> None:
    text = agent_of(spec, "reviewer").instructions

    for review_type in ("design", "code", "security", "tests"):
        assert review_type in text


def test_evolver_leaves_promotion_to_human(spec: CanonicalSpec) -> None:
    text = agent_of(spec, "evolver").instructions

    assert "seh evolve propose" in text
    assert "seh evolve benchmark" in text
    assert "seh evolve promote" in text
    assert "人間の承認" in text


@pytest.mark.parametrize("host", list(HostId))
def test_render_has_no_error_diagnostics(spec: CanonicalSpec, host: HostId, tmp_path: Path) -> None:
    plan = render(spec, host, tmp_path)

    diags = [*ADAPTERS[host].lint(plan), *lint_generated({host: plan}, {host: ADAPTERS[host]})]
    assert [d for d in diags if d.level == DiagnosticLevel.ERROR] == []


def test_claude_reviewer_tools_are_fixed_read_only(spec: CanonicalSpec, tmp_path: Path) -> None:
    text = content_of(render(spec, HostId.CLAUDE, tmp_path), "reviewer.md")

    meta = yaml.safe_load(text.split("---\n")[1])
    assert meta["tools"] == "Read, Grep, Glob"


def test_opencode_reviewer_denies_edit(spec: CanonicalSpec, tmp_path: Path) -> None:
    text = content_of(render(spec, HostId.OPENCODE, tmp_path), "reviewer.md")

    meta = yaml.safe_load(text.split("---\n")[1])
    assert meta["permission"]["edit"] == "deny"


def test_codex_agents_do_not_set_sandbox_mode(spec: CanonicalSpec, tmp_path: Path) -> None:
    plan = render(spec, HostId.CODEX, tmp_path)

    for agent_id in AGENT_IDS:
        data = tomllib.loads(content_of(plan, f"{agent_id}.toml"))
        assert "sandbox_mode" not in data
