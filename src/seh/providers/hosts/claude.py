from __future__ import annotations

import re
from pathlib import Path, PurePosixPath

import yaml

from seh.contracts import (
    AgentSpec,
    CanonicalSpec,
    CapabilityLevel,
    ChangeAction,
    Diagnostic,
    DiagnosticLevel,
    DiscoveryReport,
    GeneratedPlan,
    HostCapability,
    HostId,
    PlannedChange,
    RenderContext,
    RuleSpec,
    RuntimeCapabilityReport,
)
from seh.providers.hosts.common import (
    MANAGED_BLOCK_REASON,
    agents_md_change,
    frontmatter_document,
    managed_block,
    skill_changes,
)
from seh.providers.hosts.hooks_map import render_hooks
from seh.providers.hosts.permissions_map import map_permissions
from seh.runtime.cli_capability import ProbeSpec, probe_cli

OWNER = "host:claude"
SKILLS_DIR = ".claude/skills"
AGENTS_DIR = ".claude/agents"
RULES_DIR = ".claude/rules"
READ_ONLY_TOOLS = "Read, Grep, Glob"
# lint が plan の内容だけから read-only を判別できるよう、reason に埋め込む
AGENT_REASON = "agent"
READ_ONLY_AGENT_REASON = "agent-read-only"
WRITE_TOOLS = frozenset({"Bash", "Write", "Edit"})

# ADR-0001 §2 の Claude 既知キー
SKILL_KEYS = frozenset(
    {
        "name",
        "description",
        "when_to_use",
        "argument-hint",
        "arguments",
        "disable-model-invocation",
        "user-invocable",
        "allowed-tools",
        "disallowed-tools",
        "model",
        "effort",
        "context",
        "agent",
        "background",
        "hooks",
        "paths",
        "shell",
        "metadata",
        "license",
        "compatibility",
    }
)

_FRONTMATTER = re.compile(r"\A---\n(.*?)\n---\n", re.DOTALL)
_SKILL_PATH = re.compile(rf"^{re.escape(SKILLS_DIR)}/[^/]+/SKILL\.md$")
_AGENT_PATH = re.compile(rf"^{re.escape(AGENTS_DIR)}/[^/]+\.md$")

_CAPABILITIES = tuple(
    HostCapability(feature=feature, level=CapabilityLevel.NATIVE, reason=reason)
    for feature, reason in (
        ("instructions", "CLAUDE.md が AGENTS.md を import する"),
        ("skills", ".claude/skills/<id>/SKILL.md"),
        ("agents", ".claude/agents/<id>.md"),
        ("agents.read_only", "tools の allowlist で表現する"),
        ("rules.path_scoped", ".claude/rules の paths frontmatter"),
        ("hooks.pre_tool_use", "settings.json の hooks（生成は後続）"),
        ("permissions", "settings.json の permissions（生成は後続）"),
    )
)


def _update(path: str, content: str, reason: str) -> PlannedChange:
    return PlannedChange(
        path=path,
        action=ChangeAction.UPDATE,
        content=content.encode(),
        reason=reason,
        owner=OWNER,
    )


def _agent_change(agent: AgentSpec) -> PlannedChange:
    meta: dict[str, object] = {"name": agent.id, "description": agent.description}
    if agent.read_only:
        meta["tools"] = READ_ONLY_TOOLS
    elif agent.tools:
        meta["tools"] = ", ".join(agent.tools)
    if agent.model:
        meta["model"] = agent.model
    if agent.effort:
        meta["effort"] = agent.effort
    reason = READ_ONLY_AGENT_REASON if agent.read_only else AGENT_REASON
    return _update(
        f"{AGENTS_DIR}/{agent.id}.md", frontmatter_document(meta, agent.instructions), reason
    )


def _rule_change(rule: RuleSpec) -> PlannedChange:
    path = f"{RULES_DIR}/{rule.id}.md"
    if rule.globs:
        return _update(path, frontmatter_document({"paths": list(rule.globs)}, rule.body), "rule")
    return _update(path, f"{rule.body.rstrip()}\n", "rule")


def _rule_diagnostics(rules: tuple[RuleSpec, ...]) -> list[Diagnostic]:
    return [
        Diagnostic(
            DiagnosticLevel.WARN,
            "RULE_LOADED_ALWAYS",
            f"rule {rule.id!r} has no globs and is not always; Claude loads it every session",
            f"{RULES_DIR}/{rule.id}.md",
        )
        for rule in rules
        if not rule.globs and not rule.always
    ]


def _frontmatter(content: bytes | None) -> dict[str, object] | None:
    match = _FRONTMATTER.match((content or b"").decode(errors="replace"))
    if match is None:
        return None
    try:
        loaded = yaml.safe_load(match.group(1))
    except yaml.YAMLError:
        return None
    return loaded if isinstance(loaded, dict) else None


def _error(code: str, message: str, path: str) -> Diagnostic:
    return Diagnostic(DiagnosticLevel.ERROR, code, message, path)


def _lint_skill(change: PlannedChange) -> list[Diagnostic]:
    meta = _frontmatter(change.content)
    if meta is None:
        return [_error("UNKNOWN_SKILL_KEY", "SKILL.md frontmatter is not valid YAML", change.path)]
    return [
        _error("UNKNOWN_SKILL_KEY", f"unknown Claude skill key: {key}", change.path)
        for key in meta
        if key not in SKILL_KEYS
    ]


def _lint_agent(change: PlannedChange) -> list[Diagnostic]:
    meta = _frontmatter(change.content)
    if meta is None:
        return [_error("AGENT_MISSING_FIELD", "agent frontmatter is not valid YAML", change.path)]
    found = [
        _error("AGENT_MISSING_FIELD", f"agent frontmatter lacks {key}", change.path)
        for key in ("name", "description")
        if not meta.get(key)
    ]
    tools = {t.strip() for t in str(meta.get("tools", "")).split(",")}
    if change.reason == READ_ONLY_AGENT_REASON and tools & WRITE_TOOLS:
        found.append(
            _error(
                "READ_ONLY_AGENT_HAS_WRITE_TOOL",
                f"read-only agent has write tools: {', '.join(sorted(tools & WRITE_TOOLS))}",
                change.path,
            )
        )
    return found


def _lint_claude_md(change: PlannedChange) -> list[Diagnostic]:
    text = (change.content or b"").decode(errors="replace")
    if "@AGENTS.md" in text:
        return []
    return [_error("AGENTS_MD_NOT_IMPORTED", "CLAUDE.md does not import @AGENTS.md", change.path)]


def _lint_change(change: PlannedChange) -> list[Diagnostic]:
    if _SKILL_PATH.match(change.path):
        return _lint_skill(change)
    if _AGENT_PATH.match(change.path):
        return _lint_agent(change)
    if change.path == "CLAUDE.md":
        return _lint_claude_md(change)
    return []


def _skill_name(skill_md: Path) -> str:
    meta = _frontmatter(skill_md.read_bytes())
    name = meta.get("name") if meta else None
    return name if isinstance(name, str) and name else skill_md.parent.name


class ClaudeHostAdapter:
    id = HostId.CLAUDE

    def probe(self) -> RuntimeCapabilityReport:
        spec = ProbeSpec(
            command="claude",
            required_flags={
                "print": ("-p",),
                "output_format": ("--output-format",),
                "json_schema": ("--json-schema",),
                "allowed_tools": ("--allowedTools",),
            },
        )
        return probe_cli("claude", spec)

    def render(self, spec: CanonicalSpec, ctx: RenderContext) -> GeneratedPlan:
        changes = [
            agents_md_change(spec, owner=OWNER),
            _update("CLAUDE.md", managed_block("@AGENTS.md\n"), MANAGED_BLOCK_REASON),
        ]
        for skill in spec.skills:
            meta = {
                "name": skill.id,
                "description": skill.description,
                **skill.claude_frontmatter,
            }
            changes += skill_changes(skill, base_dir=SKILLS_DIR, meta=meta, owner=OWNER)
        changes += [_agent_change(agent) for agent in spec.agents]
        changes += [_rule_change(rule) for rule in spec.rules]
        permission_mapping = map_permissions(self.id, spec.permissions)
        changes.extend(render_hooks(self.id, permission_mapping.permissions))
        return GeneratedPlan(
            host=HostId.CLAUDE,
            changes=tuple(changes),
            diagnostics=tuple(_rule_diagnostics(spec.rules)) + permission_mapping.diagnostics,
            capabilities=_CAPABILITIES,
        )

    def lint(self, plan: GeneratedPlan) -> tuple[Diagnostic, ...]:
        return tuple(d for change in plan.changes for d in _lint_change(change))

    def discover(self, workspace: Path) -> DiscoveryReport:
        found: dict[str, list[str]] = {}
        for skill_md in sorted((workspace / SKILLS_DIR).glob("*/SKILL.md")):
            rel = PurePosixPath(skill_md.relative_to(workspace).as_posix()).as_posix()
            found.setdefault(_skill_name(skill_md), []).append(rel)
        return DiscoveryReport(
            host=HostId.CLAUDE,
            skills={name: tuple(paths) for name, paths in sorted(found.items())},
            collisions=tuple(name for name, paths in sorted(found.items()) if len(paths) > 1),
        )
