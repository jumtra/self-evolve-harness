import asyncio
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest
import yaml

from seh.contracts import (
    AgentSpec,
    CanonicalSpec,
    CapabilityLevel,
    DiagnosticLevel,
    HostId,
    PlannedChange,
    RenderContext,
    RuleSpec,
    SkillSpec,
)
from seh.providers.hosts.claude import ClaudeHostAdapter
from seh.providers.hosts.common import MANAGED_BLOCK_REASON


def _front(change: PlannedChange) -> dict[str, object]:
    assert change.content is not None
    text = change.content.decode()
    return yaml.safe_load(text.split("---\n")[1])


def _by_path(changes: tuple[PlannedChange, ...], path: str) -> PlannedChange:
    return next(c for c in changes if c.path == path)


def test_render_writes_agents_md_and_claude_md_importing_it() -> None:
    spec = CanonicalSpec(instructions="共通方針", skills=(), agents=(), rules=())
    ctx = RenderContext(root=Path("."), enabled_hosts=(HostId.CLAUDE,), project_name="p")

    plan = ClaudeHostAdapter().render(spec, ctx)

    agents_md = _by_path(plan.changes, "AGENTS.md")
    claude_md = _by_path(plan.changes, "CLAUDE.md")
    assert agents_md.content == "<!-- seh:begin -->\n共通方針\n<!-- seh:end -->\n".encode()
    assert claude_md.content == b"<!-- seh:begin -->\n@AGENTS.md\n<!-- seh:end -->\n"
    assert claude_md.reason == MANAGED_BLOCK_REASON
    assert plan.host == HostId.CLAUDE
    assert {c.owner for c in plan.changes} == {"host:claude"}


def test_render_skill_adds_claude_specific_keys_under_claude_dir() -> None:
    skill = SkillSpec(
        id="work",
        description="開発依頼を処理する",
        body="手順",
        references={"ref/a.md": "参照"},
        claude_frontmatter={"allowed-tools": "Bash", "disable-model-invocation": True},
    )
    spec = CanonicalSpec(instructions="x", skills=(skill,), agents=(), rules=())
    ctx = RenderContext(root=Path("."), enabled_hosts=(HostId.CLAUDE,), project_name="p")

    plan = ClaudeHostAdapter().render(spec, ctx)

    meta = _front(_by_path(plan.changes, ".claude/skills/work/SKILL.md"))
    assert meta == {
        "name": "work",
        "description": "開発依頼を処理する",
        "allowed-tools": "Bash",
        "disable-model-invocation": True,
    }
    assert _by_path(plan.changes, ".claude/skills/work/ref/a.md").content == "参照\n".encode()


def test_render_read_only_agent_gets_fixed_allowlist_without_bash() -> None:
    agent = AgentSpec(
        id="reviewer",
        description="レビューする",
        instructions="指示本文",
        tools=("Read", "Bash", "Edit"),
        read_only=True,
        model="sonnet",
        effort="high",
    )
    spec = CanonicalSpec(instructions="x", skills=(), agents=(agent,), rules=())
    ctx = RenderContext(root=Path("."), enabled_hosts=(HostId.CLAUDE,), project_name="p")

    plan = ClaudeHostAdapter().render(spec, ctx)

    change = _by_path(plan.changes, ".claude/agents/reviewer.md")
    assert _front(change) == {
        "name": "reviewer",
        "description": "レビューする",
        "tools": "Read, Grep, Glob",
        "model": "sonnet",
        "effort": "high",
    }
    assert change.content is not None
    assert change.content.decode().endswith("---\n\n指示本文\n")


def test_render_writable_agent_joins_tools_and_omits_empty_optionals() -> None:
    writable = AgentSpec(
        id="implementer",
        description="実装する",
        instructions="本文",
        tools=("Read", "Edit", "Bash"),
        read_only=False,
    )
    no_tools = AgentSpec(
        id="fixer", description="直す", instructions="本文", tools=(), read_only=False
    )
    spec = CanonicalSpec(instructions="x", skills=(), agents=(writable, no_tools), rules=())
    ctx = RenderContext(root=Path("."), enabled_hosts=(HostId.CLAUDE,), project_name="p")

    plan = ClaudeHostAdapter().render(spec, ctx)

    assert _front(_by_path(plan.changes, ".claude/agents/implementer.md")) == {
        "name": "implementer",
        "description": "実装する",
        "tools": "Read, Edit, Bash",
    }
    assert _front(_by_path(plan.changes, ".claude/agents/fixer.md")) == {
        "name": "fixer",
        "description": "直す",
    }


def test_render_rules_cover_paths_always_and_model_decision() -> None:
    scoped = RuleSpec(id="py", description="d", body="Python規約", globs=("src/**/*.py", "a.py"))
    always = RuleSpec(id="core", description="d", body="常時", always=True)
    other = RuleSpec(id="misc", description="d", body="任意")
    spec = CanonicalSpec(instructions="x", skills=(), agents=(), rules=(scoped, always, other))
    ctx = RenderContext(root=Path("."), enabled_hosts=(HostId.CLAUDE,), project_name="p")

    plan = ClaudeHostAdapter().render(spec, ctx)

    assert _front(_by_path(plan.changes, ".claude/rules/py.md")) == {
        "paths": ["src/**/*.py", "a.py"]
    }
    assert _by_path(plan.changes, ".claude/rules/core.md").content == "常時\n".encode()
    assert _by_path(plan.changes, ".claude/rules/misc.md").content == "任意\n".encode()
    warnings = [d for d in plan.diagnostics if d.code == "RULE_LOADED_ALWAYS"]
    assert [(d.level, d.path) for d in warnings] == [
        (DiagnosticLevel.WARN, ".claude/rules/misc.md")
    ]


def test_render_reports_native_capabilities() -> None:
    spec = CanonicalSpec(instructions="x", skills=(), agents=(), rules=())
    ctx = RenderContext(root=Path("."), enabled_hosts=(HostId.CLAUDE,), project_name="p")

    plan = ClaudeHostAdapter().render(spec, ctx)

    levels = {c.feature: c.level for c in plan.capabilities}
    assert levels == {
        "instructions": CapabilityLevel.NATIVE,
        "skills": CapabilityLevel.NATIVE,
        "agents": CapabilityLevel.NATIVE,
        "agents.read_only": CapabilityLevel.NATIVE,
        "rules.path_scoped": CapabilityLevel.NATIVE,
        "hooks.pre_tool_use": CapabilityLevel.NATIVE,
        "permissions": CapabilityLevel.NATIVE,
    }


def test_render_does_not_spawn_subprocesses(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*args: object, **kwargs: object) -> None:
        raise AssertionError("subprocess must not be started")

    monkeypatch.setattr(subprocess, "run", boom)
    monkeypatch.setattr(subprocess, "Popen", boom)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", boom)
    spec = CanonicalSpec(
        instructions="x",
        skills=(SkillSpec(id="a", description="d", body="b"),),
        agents=(AgentSpec(id="r", description="d", instructions="i", tools=(), read_only=True),),
        rules=(RuleSpec(id="q", description="d", body="b", always=True),),
    )
    ctx = RenderContext(root=Path("."), enabled_hosts=(HostId.CLAUDE,), project_name="p")
    adapter = ClaudeHostAdapter()

    plan = adapter.render(spec, ctx)
    adapter.lint(plan)

    assert plan.changes


def test_lint_accepts_a_freshly_rendered_plan() -> None:
    spec = CanonicalSpec(
        instructions="x",
        skills=(
            SkillSpec(
                id="a",
                description="d",
                body="b",
                claude_frontmatter={"allowed-tools": "Bash", "when_to_use": "いつか"},
            ),
        ),
        agents=(
            AgentSpec(id="r", description="d", instructions="i", tools=("Bash",), read_only=True),
            AgentSpec(id="w", description="d", instructions="i", tools=("Bash",), read_only=False),
        ),
        rules=(),
    )
    ctx = RenderContext(root=Path("."), enabled_hosts=(HostId.CLAUDE,), project_name="p")
    adapter = ClaudeHostAdapter()

    diagnostics = adapter.lint(adapter.render(spec, ctx))

    assert diagnostics == ()


def test_lint_flags_unknown_skill_key() -> None:
    spec = CanonicalSpec(
        instructions="x",
        skills=(SkillSpec(id="a", description="d", body="b", claude_frontmatter={"bogus-key": 1}),),
        agents=(),
        rules=(),
    )
    ctx = RenderContext(root=Path("."), enabled_hosts=(HostId.CLAUDE,), project_name="p")
    adapter = ClaudeHostAdapter()

    diagnostics = adapter.lint(adapter.render(spec, ctx))

    assert [(d.level, d.code, d.path) for d in diagnostics] == [
        (DiagnosticLevel.ERROR, "UNKNOWN_SKILL_KEY", ".claude/skills/a/SKILL.md")
    ]


def test_lint_flags_agent_missing_name_and_description() -> None:
    spec = CanonicalSpec(instructions="x", skills=(), agents=(), rules=())
    ctx = RenderContext(root=Path("."), enabled_hosts=(HostId.CLAUDE,), project_name="p")
    adapter = ClaudeHostAdapter()
    plan = adapter.render(spec, ctx)
    broken = PlannedChange(
        path=".claude/agents/x.md",
        action=plan.changes[0].action,
        content=b"---\ntools: Read\n---\n\nbody\n",
        reason="agent",
        owner="host:claude",
    )

    diagnostics = adapter.lint(replace(plan, changes=(*plan.changes, broken)))

    assert [(d.level, d.code, d.path) for d in diagnostics] == [
        (DiagnosticLevel.ERROR, "AGENT_MISSING_FIELD", ".claude/agents/x.md"),
        (DiagnosticLevel.ERROR, "AGENT_MISSING_FIELD", ".claude/agents/x.md"),
    ]


def test_lint_flags_write_tool_on_read_only_agent() -> None:
    spec = CanonicalSpec(instructions="x", skills=(), agents=(), rules=())
    ctx = RenderContext(root=Path("."), enabled_hosts=(HostId.CLAUDE,), project_name="p")
    adapter = ClaudeHostAdapter()
    plan = adapter.render(spec, ctx)
    broken = PlannedChange(
        path=".claude/agents/r.md",
        action=plan.changes[0].action,
        content=b"---\nname: r\ndescription: d\ntools: Read, Bash\n---\n\nbody\n",
        reason="agent-read-only",
        owner="host:claude",
    )

    diagnostics = adapter.lint(replace(plan, changes=(*plan.changes, broken)))

    assert [(d.level, d.code) for d in diagnostics] == [
        (DiagnosticLevel.ERROR, "READ_ONLY_AGENT_HAS_WRITE_TOOL")
    ]


def test_lint_flags_claude_md_without_agents_md_import() -> None:
    spec = CanonicalSpec(instructions="x", skills=(), agents=(), rules=())
    ctx = RenderContext(root=Path("."), enabled_hosts=(HostId.CLAUDE,), project_name="p")
    adapter = ClaudeHostAdapter()
    plan = adapter.render(spec, ctx)
    changes = tuple(
        replace(c, content=b"<!-- seh:begin -->\nhello\n<!-- seh:end -->\n")
        if c.path == "CLAUDE.md"
        else c
        for c in plan.changes
    )

    diagnostics = adapter.lint(replace(plan, changes=changes))

    assert [(d.level, d.code, d.path) for d in diagnostics] == [
        (DiagnosticLevel.ERROR, "AGENTS_MD_NOT_IMPORTED", "CLAUDE.md")
    ]


def test_discover_lists_skill_names_and_reports_collisions(tmp_path: Path) -> None:
    (tmp_path / ".claude/skills/alpha").mkdir(parents=True)
    (tmp_path / ".claude/skills/alpha/SKILL.md").write_text("---\nname: alpha\n---\nx\n")
    (tmp_path / ".claude/skills/nameless").mkdir(parents=True)
    (tmp_path / ".claude/skills/nameless/SKILL.md").write_text("no frontmatter\n")
    (tmp_path / ".claude/skills/dup-a").mkdir(parents=True)
    (tmp_path / ".claude/skills/dup-a/SKILL.md").write_text("---\nname: dup\n---\nx\n")
    (tmp_path / ".claude/skills/dup-b").mkdir(parents=True)
    (tmp_path / ".claude/skills/dup-b/SKILL.md").write_text("---\nname: dup\n---\nx\n")

    report = ClaudeHostAdapter().discover(tmp_path)

    assert report.host == HostId.CLAUDE
    assert dict(report.skills) == {
        "alpha": (".claude/skills/alpha/SKILL.md",),
        "dup": (".claude/skills/dup-a/SKILL.md", ".claude/skills/dup-b/SKILL.md"),
        "nameless": (".claude/skills/nameless/SKILL.md",),
    }
    assert report.collisions == ("dup",)


def test_discover_on_workspace_without_skills_is_empty(tmp_path: Path) -> None:
    report = ClaudeHostAdapter().discover(tmp_path)

    assert dict(report.skills) == {}
    assert report.collisions == ()


def test_probe_reports_not_installed_when_claude_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("shutil.which", lambda _name: None)

    report = ClaudeHostAdapter().probe()

    assert report.host == "claude"
    assert report.installed is False
    assert set(report.capabilities) == {"print", "output_format", "json_schema", "allowed_tools"}
