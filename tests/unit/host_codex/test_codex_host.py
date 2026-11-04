import tomllib
from dataclasses import replace
from pathlib import Path

import pytest

from seh.contracts import (
    AgentSpec,
    CanonicalSpec,
    CapabilityLevel,
    DiagnosticLevel,
    GeneratedPlan,
    HostId,
    PlannedChange,
    RenderContext,
    RuleSpec,
    SkillSpec,
)
from seh.providers.hosts import codex as codex_module
from seh.providers.hosts.codex import CodexHostAdapter
from seh.providers.hosts.common import MANAGED_BLOCK_REASON

OWNER = "host:codex"
READ_ONLY_NOTE = "ファイルを編集・作成・削除してはならない（読み取り専用）。"


def make_spec(
    *, instructions: str = "共通方針", read_only: bool = True, effort: str | None = None
) -> CanonicalSpec:
    return CanonicalSpec(
        instructions=instructions,
        skills=(
            SkillSpec(
                id="work",
                description="開発依頼を処理する",
                body="手順",
                claude_frontmatter={"allowed-tools": "Bash"},
            ),
        ),
        agents=(
            AgentSpec(
                id="reviewer",
                description="差分をレビューする",
                instructions="観点に沿って確認する",
                tools=("Read", "Grep"),
                read_only=read_only,
                model="claude-opus",
                effort=effort,
            ),
        ),
        rules=(RuleSpec(id="python", description="Python 規約", body="本文", globs=("**/*.py",)),),
    )


def render(spec: CanonicalSpec, tmp_path: Path) -> GeneratedPlan:
    ctx = RenderContext(root=tmp_path, enabled_hosts=(HostId.CODEX,), project_name="demo")
    return CodexHostAdapter().render(spec, ctx)


def change_at(plan: GeneratedPlan, path: str) -> PlannedChange:
    return next(c for c in plan.changes if c.path == path)


def agent_toml(plan: GeneratedPlan) -> dict[str, object]:
    content = change_at(plan, ".codex/agents/reviewer.toml").content
    assert content is not None
    return tomllib.loads(content.decode())


def with_content(plan: GeneratedPlan, path: str, content: str) -> GeneratedPlan:
    changes = tuple(
        replace(c, content=content.encode()) if c.path == path else c for c in plan.changes
    )
    return replace(plan, changes=changes)


def error_codes(plan: GeneratedPlan) -> set[str]:
    diagnostics = CodexHostAdapter().lint(plan)
    return {d.code for d in diagnostics if d.level is DiagnosticLevel.ERROR}


def test_render_writes_agents_md_as_managed_block(tmp_path: Path) -> None:
    plan = render(make_spec(), tmp_path)

    change = change_at(plan, "AGENTS.md")

    assert change.reason == MANAGED_BLOCK_REASON
    assert change.owner == OWNER
    assert change.content == "<!-- seh:begin -->\n共通方針\n<!-- seh:end -->\n".encode()


def test_render_reports_error_when_agents_md_exceeds_32kib(tmp_path: Path) -> None:
    plan = render(make_spec(instructions="a" * 33_000), tmp_path)

    assert "AGENTS_MD_TOO_LARGE" in {d.code for d in plan.diagnostics}


def test_render_does_not_report_error_for_small_agents_md(tmp_path: Path) -> None:
    plan = render(make_spec(), tmp_path)

    assert plan.diagnostics == ()


def test_render_writes_shared_skill_without_claude_specific_keys(tmp_path: Path) -> None:
    plan = render(make_spec(), tmp_path)

    change = change_at(plan, ".agents/skills/work/SKILL.md")

    assert change.owner == OWNER
    assert (
        change.content == "---\nname: work\ndescription: 開発依頼を処理する\n---\n\n手順\n".encode()
    )


def test_render_generates_skills_only_under_shared_dir(tmp_path: Path) -> None:
    plan = render(make_spec(), tmp_path)

    skill_paths = [c.path for c in plan.changes if "SKILL.md" in c.path]

    assert skill_paths == [".agents/skills/work/SKILL.md"]


def test_render_does_not_generate_openai_yaml(tmp_path: Path) -> None:
    plan = render(make_spec(), tmp_path)

    assert not [c.path for c in plan.changes if c.path.endswith("openai.yaml")]


def test_render_agent_toml_has_required_keys(tmp_path: Path) -> None:
    plan = render(make_spec(), tmp_path)

    data = agent_toml(plan)

    assert data["name"] == "reviewer"
    assert data["description"] == "差分をレビューする"
    assert str(data["developer_instructions"]).startswith("観点に沿って確認する")
    assert change_at(plan, ".codex/agents/reviewer.toml").owner == OWNER


def test_render_read_only_agent_appends_read_only_note(tmp_path: Path) -> None:
    plan = render(make_spec(read_only=True), tmp_path)

    assert str(agent_toml(plan)["developer_instructions"]).rstrip().endswith(READ_ONLY_NOTE)


def test_render_writable_agent_has_no_read_only_note(tmp_path: Path) -> None:
    plan = render(make_spec(read_only=False), tmp_path)

    assert READ_ONLY_NOTE not in str(agent_toml(plan)["developer_instructions"])


@pytest.mark.parametrize("key", ["sandbox_mode", "approval_policy", "model"])
def test_render_agent_toml_omits_ineffective_keys(tmp_path: Path, key: str) -> None:
    plan = render(make_spec(), tmp_path)

    assert key not in agent_toml(plan)


def test_render_agent_toml_maps_effort_to_reasoning_effort(tmp_path: Path) -> None:
    plan = render(make_spec(effort="high"), tmp_path)

    assert agent_toml(plan)["model_reasoning_effort"] == "high"


def test_render_agent_toml_omits_reasoning_effort_without_effort(tmp_path: Path) -> None:
    plan = render(make_spec(effort=None), tmp_path)

    assert "model_reasoning_effort" not in agent_toml(plan)


def test_render_does_not_generate_rule_files(tmp_path: Path) -> None:
    plan = render(make_spec(), tmp_path)

    assert sorted(c.path for c in plan.changes) == [
        ".agents/skills/work/SKILL.md",
        ".codex/agents/reviewer.toml",
        ".codex/hooks.json",
        "AGENTS.md",
    ]


@pytest.mark.parametrize(
    ("feature", "level"),
    [
        ("instructions", CapabilityLevel.NATIVE),
        ("skills", CapabilityLevel.NATIVE),
        ("agents", CapabilityLevel.ADAPTED),
        ("agents.read_only", CapabilityLevel.ADAPTED),
        ("rules.path_scoped", CapabilityLevel.CI_ONLY),
        ("hooks.pre_tool_use", CapabilityLevel.ADAPTED),
        ("permissions", CapabilityLevel.ADAPTED),
    ],
)
def test_render_declares_capability_levels(
    tmp_path: Path, feature: str, level: CapabilityLevel
) -> None:
    plan = render(make_spec(), tmp_path)

    capabilities = {c.feature: c for c in plan.capabilities}

    assert capabilities[feature].level is level
    assert capabilities[feature].reason


def test_render_plan_is_for_codex_host(tmp_path: Path) -> None:
    plan = render(make_spec(), tmp_path)

    assert plan.host is HostId.CODEX


def test_lint_accepts_rendered_plan(tmp_path: Path) -> None:
    plan = render(make_spec(), tmp_path)

    assert CodexHostAdapter().lint(plan) == ()


@pytest.mark.parametrize("missing", ["name", "description", "developer_instructions"])
def test_lint_reports_agent_missing_required_key(tmp_path: Path, missing: str) -> None:
    plan = render(make_spec(), tmp_path)
    data = {"name": "r", "description": "d", "developer_instructions": "i"}
    del data[missing]
    body = "".join(f'{k} = "{v}"\n' for k, v in data.items())

    broken = with_content(plan, ".codex/agents/reviewer.toml", body)

    assert "CODEX_AGENT_MISSING_KEY" in error_codes(broken)


def test_lint_reports_unparsable_agent_toml(tmp_path: Path) -> None:
    plan = render(make_spec(), tmp_path)

    broken = with_content(plan, ".codex/agents/reviewer.toml", "name = = oops")

    assert "CODEX_AGENT_INVALID_TOML" in error_codes(broken)


@pytest.mark.parametrize("key", ["sandbox_mode", "approval_policy"])
def test_lint_reports_ineffective_agent_key(tmp_path: Path, key: str) -> None:
    plan = render(make_spec(), tmp_path)
    body = f'name = "r"\ndescription = "d"\ndeveloper_instructions = "i"\n{key} = "read-only"\n'

    broken = with_content(plan, ".codex/agents/reviewer.toml", body)

    assert "CODEX_AGENT_INEFFECTIVE_KEY" in error_codes(broken)


def test_lint_reports_extra_key_in_shared_skill(tmp_path: Path) -> None:
    plan = render(make_spec(), tmp_path)
    skill = "---\nname: work\ndescription: d\nallowed-tools: Bash\n---\n\n本文\n"

    broken = with_content(plan, ".agents/skills/work/SKILL.md", skill)

    assert "SHARED_SKILL_EXTRA_KEY" in error_codes(broken)


def test_lint_reports_oversized_agents_md(tmp_path: Path) -> None:
    plan = render(make_spec(), tmp_path)

    broken = with_content(plan, "AGENTS.md", "a" * 33_000)

    assert "AGENTS_MD_TOO_LARGE" in error_codes(broken)


def test_discover_lists_skills_under_shared_dir(tmp_path: Path) -> None:
    skill_dir = tmp_path / ".agents/skills/work"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("---\nname: work\ndescription: d\n---\n\n本文\n")

    report = CodexHostAdapter().discover(tmp_path)

    assert report.host is HostId.CODEX
    assert dict(report.skills) == {"work": (".agents/skills/work/SKILL.md",)}
    assert report.collisions == ()


def test_discover_reports_collision_when_two_dirs_declare_same_name(tmp_path: Path) -> None:
    for directory in ("work", "work-copy"):
        skill_dir = tmp_path / ".agents/skills" / directory
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text("---\nname: work\ndescription: d\n---\n\n本文\n")

    report = CodexHostAdapter().discover(tmp_path)

    assert report.collisions == ("work",)
    assert len(report.skills["work"]) == 2


def test_discover_returns_empty_report_without_skills_dir(tmp_path: Path) -> None:
    report = CodexHostAdapter().discover(tmp_path)

    assert dict(report.skills) == {}
    assert report.collisions == ()


def test_probe_reports_not_installed_when_codex_is_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("seh.runtime.cli_capability.shutil.which", lambda _command: None)

    report = CodexHostAdapter().probe()

    assert report.host == "codex"
    assert report.installed is False
    assert set(report.capabilities) == {"json", "output_schema", "sandbox", "cd"}


def test_render_lint_discover_do_not_spawn_subprocesses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("subprocess must not be started")

    monkeypatch.setattr("subprocess.Popen", forbidden)
    monkeypatch.setattr("asyncio.create_subprocess_exec", forbidden)
    adapter = CodexHostAdapter()

    plan = render(make_spec(), tmp_path)
    adapter.lint(plan)
    adapter.discover(tmp_path)

    assert plan.changes


def test_adapter_id_and_module_expose_codex() -> None:
    assert CodexHostAdapter.id is HostId.CODEX
    assert codex_module.CodexHostAdapter is CodexHostAdapter
