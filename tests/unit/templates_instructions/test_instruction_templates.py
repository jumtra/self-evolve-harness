import re
from pathlib import Path

import pytest
import yaml

import seh
from seh.authoring.lint import lint_spec
from seh.contracts import DiagnosticLevel, HostId, RenderContext
from seh.doctor import DoctorContext
from seh.doctor.check_context import V1_BASELINE_CHARS, run
from seh.init.templating import render_template_text
from seh.providers.hosts.claude import ClaudeHostAdapter
from seh.spec_loader import load_spec

TEMPLATE_SPEC = Path(seh.__file__).parent / "templates" / "spec"
CORE_LIMIT = 2_000
PLACEHOLDER = re.compile(r"\{\{[^}]*\}\}")


def build_spec_dir(tmp_path: Path, variables: dict[str, str]) -> Path:
    spec_dir = tmp_path / "spec"
    (spec_dir / "instructions").mkdir(parents=True)
    (spec_dir / "rules").mkdir()
    for relative in (
        "instructions/core.md",
        "rules/engineering.md",
        "rules/testing.md",
    ):
        raw = (TEMPLATE_SPEC / relative).read_text(encoding="utf-8")
        (spec_dir / relative).write_text(render_template_text(raw, variables), encoding="utf-8")
    return spec_dir


def test_core_template_within_character_limit() -> None:
    raw = (TEMPLATE_SPEC / "instructions" / "core.md").read_text(encoding="utf-8")

    assert len(raw) <= CORE_LIMIT


@pytest.mark.parametrize(
    "relative", ["instructions/core.md", "rules/engineering.md", "rules/testing.md"]
)
def test_template_uses_only_the_four_known_variables(relative: str) -> None:
    raw = (TEMPLATE_SPEC / relative).read_text(encoding="utf-8")

    names = {m[2:-2].strip() for m in PLACEHOLDER.findall(raw)}

    assert names <= {"project_name", "ci_check_cmd", "ci_fix_cmd", "protected_configs"}


def test_core_substitutes_ci_commands_and_protected_configs(tmp_path: Path) -> None:
    spec = load_spec(
        build_spec_dir(
            tmp_path,
            {
                "project_name": "demo",
                "ci_check_cmd": "uv run pytest",
                "ci_fix_cmd": "uv run ruff check --fix",
                "protected_configs": "pyproject.toml, ruff.toml",
            },
        )
    )

    assert "CI_CHECK_CMD: `uv run pytest`" in spec.instructions
    assert "CI_FIX_CMD: `uv run ruff check --fix`" in spec.instructions
    assert "pyproject.toml, ruff.toml" in spec.instructions


def test_rendered_templates_have_no_leftover_placeholder(tmp_path: Path) -> None:
    spec = load_spec(
        build_spec_dir(
            tmp_path,
            {
                "project_name": "demo",
                "ci_check_cmd": "uv run pytest",
                "ci_fix_cmd": "uv run ruff check --fix",
                "protected_configs": "pyproject.toml, ruff.toml",
            },
        )
    )

    texts = [spec.instructions, *(r.body for r in spec.rules)]

    assert [t for t in texts if "{{" in t] == []


def test_spec_loads_engineering_and_testing_rules_with_globs(tmp_path: Path) -> None:
    spec = load_spec(
        build_spec_dir(
            tmp_path,
            {
                "project_name": "demo",
                "ci_check_cmd": "uv run pytest",
                "ci_fix_cmd": "uv run ruff check --fix",
                "protected_configs": "pyproject.toml, ruff.toml",
            },
        )
    )

    rules = {r.id: r for r in spec.rules}
    assert sorted(rules) == ["engineering", "testing"]
    assert "src/**" in rules["engineering"].globs
    assert "tests/**" in rules["testing"].globs
    assert not rules["engineering"].always and not rules["testing"].always


def test_lint_spec_reports_no_error(tmp_path: Path) -> None:
    spec = load_spec(
        build_spec_dir(
            tmp_path,
            {
                "project_name": "demo",
                "ci_check_cmd": "uv run pytest",
                "ci_fix_cmd": "uv run ruff check --fix",
                "protected_configs": "pyproject.toml, ruff.toml",
            },
        )
    )

    errors = [d for d in lint_spec(spec) if d.level == DiagnosticLevel.ERROR]

    assert errors == []


def test_lint_spec_reports_no_warning(tmp_path: Path) -> None:
    spec = load_spec(
        build_spec_dir(
            tmp_path,
            {
                "project_name": "demo",
                "ci_check_cmd": "uv run pytest",
                "ci_fix_cmd": "uv run ruff check --fix",
                "protected_configs": "pyproject.toml, ruff.toml",
            },
        )
    )

    warnings = [d for d in lint_spec(spec) if d.level == DiagnosticLevel.WARN]

    assert warnings == []


def test_core_points_to_entrypoints_and_authoring_rules(tmp_path: Path) -> None:
    spec = load_spec(
        build_spec_dir(
            tmp_path,
            {
                "project_name": "demo",
                "ci_check_cmd": "uv run pytest",
                "ci_fix_cmd": "uv run ruff check --fix",
                "protected_configs": "pyproject.toml, ruff.toml",
            },
        )
    )

    assert "/work" in spec.instructions
    assert "seh work run --mode managed" in spec.instructions
    assert "seh author" in spec.instructions
    assert ".harness/spec" in spec.instructions
    assert ".harness/knowledge/domain.md" in spec.instructions


@pytest.mark.parametrize("rule_id", ["engineering", "testing"])
def test_claude_rule_is_path_scoped_with_paths_frontmatter(tmp_path: Path, rule_id: str) -> None:
    spec = load_spec(
        build_spec_dir(
            tmp_path,
            {
                "project_name": "demo",
                "ci_check_cmd": "uv run pytest",
                "ci_fix_cmd": "uv run ruff check --fix",
                "protected_configs": "pyproject.toml, ruff.toml",
            },
        )
    )
    ctx = RenderContext(root=tmp_path / "out", enabled_hosts=(HostId.CLAUDE,), project_name="demo")

    plan = ClaudeHostAdapter().render(spec, ctx)

    change = next(c for c in plan.changes if c.path == f".claude/rules/{rule_id}.md")
    meta = yaml.safe_load((change.content or b"").decode().split("---\n")[1])
    assert meta["paths"]


def test_always_loaded_context_is_below_v1_baseline(tmp_path: Path) -> None:
    spec = load_spec(
        build_spec_dir(
            tmp_path,
            {
                "project_name": "demo",
                "ci_check_cmd": "uv run pytest",
                "ci_fix_cmd": "uv run ruff check --fix",
                "protected_configs": "pyproject.toml, ruff.toml",
            },
        )
    )
    out = tmp_path / "out"
    out.mkdir()
    ctx = RenderContext(root=out, enabled_hosts=(HostId.CLAUDE,), project_name="demo")
    plan = ClaudeHostAdapter().render(spec, ctx)
    for change in plan.changes:
        if change.content is None or change.path.startswith(".claude/skills/"):
            continue
        target = out / change.path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(change.content)

    findings = run(DoctorContext(root=out, options={"context": True}))

    size = next(f for f in findings if f.code == "CONTEXT_SIZE")
    found = re.search(r"文字数 (\d+)", size.message)
    assert found is not None
    chars = int(found.group(1))
    assert chars < V1_BASELINE_CHARS
