import shutil
from pathlib import Path

import pytest

import seh
from seh.authoring.lint import lint_generated, lint_spec
from seh.contracts import CanonicalSpec, DiagnosticLevel, HostAdapter, HostId, RenderContext
from seh.providers.hosts.antigravity import AntigravityHostAdapter
from seh.providers.hosts.claude import ClaudeHostAdapter
from seh.providers.hosts.codex import CodexHostAdapter
from seh.providers.hosts.opencode import OpenCodeHostAdapter
from seh.spec_loader import load_spec

TEMPLATE_SKILLS = Path(seh.__file__).parent / "templates" / "spec" / "skills"
SKILL_IDS = ("work", "harness-init")
ADAPTERS: dict[HostId, HostAdapter] = {
    HostId.CLAUDE: ClaudeHostAdapter(),
    HostId.ANTIGRAVITY: AntigravityHostAdapter(),
    HostId.CODEX: CodexHostAdapter(),
    HostId.OPENCODE: OpenCodeHostAdapter(),
}
BODY_LIMIT = 2_500


@pytest.fixture
def spec(tmp_path: Path) -> CanonicalSpec:
    spec_dir = tmp_path / "spec"
    (spec_dir / "instructions").mkdir(parents=True)
    (spec_dir / "instructions" / "core.md").write_text("共通方針\n", encoding="utf-8")
    shutil.copytree(TEMPLATE_SKILLS, spec_dir / "skills")
    return load_spec(spec_dir)


def body_of(spec: CanonicalSpec, skill_id: str) -> str:
    return next(s.body for s in spec.skills if s.id == skill_id)


def test_loads_exactly_the_two_public_skills(spec: CanonicalSpec) -> None:
    assert sorted(s.id for s in spec.skills) == sorted(SKILL_IDS)


def test_lint_spec_reports_no_error(spec: CanonicalSpec) -> None:
    errors = [d for d in lint_spec(spec) if d.level == DiagnosticLevel.ERROR]

    assert errors == []


def test_lint_spec_reports_no_warning(spec: CanonicalSpec) -> None:
    warnings = [d for d in lint_spec(spec) if d.level == DiagnosticLevel.WARN]

    assert warnings == []


@pytest.mark.parametrize("host", list(HostId))
def test_render_has_no_error_diagnostics(spec: CanonicalSpec, host: HostId, tmp_path: Path) -> None:
    ctx = RenderContext(root=tmp_path, enabled_hosts=(host,), project_name="demo")
    adapter = ADAPTERS[host]

    plan = adapter.render(spec, ctx)

    diags = [*adapter.lint(plan), *lint_generated({host: plan}, {host: adapter})]
    assert [d for d in diags if d.level == DiagnosticLevel.ERROR] == []


def test_shared_skill_path_has_no_claude_only_keys(spec: CanonicalSpec, tmp_path: Path) -> None:
    ctx = RenderContext(root=tmp_path, enabled_hosts=(HostId.CODEX,), project_name="demo")

    plan = CodexHostAdapter().render(spec, ctx)

    shared = [c for c in plan.changes if c.path.startswith(".agents/skills/") and c.content]
    assert len(shared) >= len(SKILL_IDS)
    for change in shared:
        assert b"disable-model-invocation" not in (change.content or b"")


def test_work_requires_evidence_before_completion(spec: CanonicalSpec) -> None:
    assert "完了宣言は証拠の提示が前提" in body_of(spec, "work")


def test_work_does_not_run_approval_required_operations(spec: CanonicalSpec) -> None:
    assert "承認が必要な操作は実行しない" in body_of(spec, "work")


def test_harness_init_leaves_apply_to_user_terminal(spec: CanonicalSpec) -> None:
    assert "apply はユーザーのターミナルで" in body_of(spec, "harness-init")


def test_harness_init_is_user_invoked_only(spec: CanonicalSpec) -> None:
    skill = next(s for s in spec.skills if s.id == "harness-init")

    assert skill.claude_frontmatter == {"disable-model-invocation": True}


def test_work_references_managed_task_guide(spec: CanonicalSpec) -> None:
    skill = next(s for s in spec.skills if s.id == "work")

    assert "references/managed-task.md" in skill.body
    assert "references/managed-task.md" in skill.references


@pytest.mark.parametrize("skill_id", SKILL_IDS)
def test_body_stays_short(spec: CanonicalSpec, skill_id: str) -> None:
    assert len(body_of(spec, skill_id)) <= BODY_LIMIT


@pytest.mark.parametrize("skill_id", SKILL_IDS)
def test_body_has_no_template_variables(spec: CanonicalSpec, skill_id: str) -> None:
    assert "{{" not in body_of(spec, skill_id)
