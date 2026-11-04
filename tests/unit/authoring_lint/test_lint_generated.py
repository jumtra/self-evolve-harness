from pathlib import Path

from seh.authoring.lint import has_errors, lint_generated
from seh.contracts import (
    CanonicalSpec,
    ChangeAction,
    DiagnosticLevel,
    GeneratedPlan,
    HostId,
    PlannedChange,
    RenderContext,
    SkillSpec,
)
from seh.providers.hosts.antigravity import AntigravityHostAdapter
from seh.providers.hosts.claude import ClaudeHostAdapter
from seh.providers.hosts.codex import CodexHostAdapter
from seh.providers.hosts.opencode import OpenCodeHostAdapter

BODY = "## Goal\na\n## Inputs\nb\n## Boundaries\nc\n## Output\nd\n## Feedback\ne\n"


def test_real_adapters_render_without_errors_and_no_claude_key_leak() -> None:
    skill = SkillSpec(
        id="deploy-app",
        description="Use when deploying",
        body=BODY,
        claude_frontmatter={"allowed-tools": "Read", "disable-model-invocation": True},
    )
    spec = CanonicalSpec(instructions="共通方針", skills=(skill,), agents=(), rules=())
    hosts = (HostId.CLAUDE, HostId.ANTIGRAVITY, HostId.CODEX, HostId.OPENCODE)
    ctx = RenderContext(root=Path("."), enabled_hosts=hosts, project_name="p")
    adapters = {
        HostId.CLAUDE: ClaudeHostAdapter(),
        HostId.ANTIGRAVITY: AntigravityHostAdapter(),
        HostId.CODEX: CodexHostAdapter(),
        HostId.OPENCODE: OpenCodeHostAdapter(),
    }
    plans = {host: adapter.render(spec, ctx) for host, adapter in adapters.items()}

    diags = lint_generated(plans, adapters)

    assert not has_errors(diags)
    assert "CLAUDE_KEY_LEAKED" not in [d.code for d in diags]


def test_claude_key_in_shared_skill_is_error() -> None:
    leaked = PlannedChange(
        path=".agents/skills/deploy-app/SKILL.md",
        action=ChangeAction.CREATE,
        content=b"---\nname: deploy-app\ndescription: d\nallowed-tools: Bash\n---\nbody\n",
        reason="skill",
        owner="host:codex",
    )
    plan = GeneratedPlan(host=HostId.CODEX, changes=(leaked,), diagnostics=(), capabilities=())
    adapters = {HostId.CODEX: CodexHostAdapter()}

    diags = lint_generated({HostId.CODEX: plan}, adapters)

    leak = [d for d in diags if d.code == "CLAUDE_KEY_LEAKED"]
    assert len(leak) == 1
    assert leak[0].level == DiagnosticLevel.ERROR
    assert leak[0].path == ".agents/skills/deploy-app/SKILL.md"


def test_adapter_diagnostics_are_prefixed_with_host() -> None:
    bad = PlannedChange(
        path=".claude/skills/x/SKILL.md",
        action=ChangeAction.CREATE,
        content=b"---\nbogus: 1\n---\nbody\n",
        reason="skill",
        owner="host:claude",
    )
    plan = GeneratedPlan(host=HostId.CLAUDE, changes=(bad,), diagnostics=(), capabilities=())
    adapters = {HostId.CLAUDE: ClaudeHostAdapter()}

    diags = lint_generated({HostId.CLAUDE: plan}, adapters)

    assert diags
    assert all(d.code.startswith("claude:") for d in diags)
    assert has_errors(diags)
