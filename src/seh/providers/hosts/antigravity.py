from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
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
    agents_md_change,
    frontmatter_document,
    shared_skill_changes,
)
from seh.runtime.cli_capability import ProbeSpec, probe_cli

_OWNER = "host:antigravity"
_RULES_DIR = ".agents/rules"
_AGENTS_DIR = ".agents/agents"
_SKILL_DIRS = (".agents/skills", ".agent/skills")
_RULE_MAX_BYTES = 24_000
_TRIGGERS = frozenset({"always_on", "model_decision", "glob", "manual"})
_SKILL_KEYS = frozenset({"name", "description"})
_READ_ONLY_NOTE = "ファイルを編集しないこと（読み取り専用）"

_PROBE = ProbeSpec(
    command="agy",
    required_flags={
        "print": ("-p",),
        "output_format": ("--output-format",),
        "json_schema": ("--json-schema",),
    },
)


def _capability(feature: str, level: CapabilityLevel, reason: str) -> HostCapability:
    return HostCapability(feature=feature, level=level, reason=reason)


_CAPABILITIES = (
    _capability("instructions", CapabilityLevel.NATIVE, "AGENTS.md を読む"),
    _capability("skills", CapabilityLevel.NATIVE, ".agents/skills を読む"),
    _capability("agents", CapabilityLevel.UNVERIFIED, ".agents/agents の実効性は未検証"),
    _capability(
        "agents.read_only",
        CapabilityLevel.UNVERIFIED,
        "commandExecutionPolicy による読み取り専用化の実効性は未検証",
    ),
    _capability("rules.path_scoped", CapabilityLevel.NATIVE, "trigger: glob で対象を絞れる"),
    _capability(
        "hooks.pre_tool_use",
        CapabilityLevel.ADAPTED,
        "実効性は UNVERIFIED。生成は後続タスク（T49）",
    ),
    _capability(
        "permissions",
        CapabilityLevel.UNSUPPORTED,
        "プロジェクト単位の権限設定の所在が未確認。ユーザー設定 ~/.gemini には書かない",
    ),
    _capability(
        "runtime.managed",
        CapabilityLevel.UNSUPPORTED,
        "POLICY_BLOCKED: consumer plan では第三者ラッピング非対応",
    ),
)


def _rule_meta(rule: RuleSpec) -> dict[str, object]:
    if rule.always:
        return {"trigger": "always_on"}
    if rule.globs:
        return {"trigger": "glob", "globs": ",".join(rule.globs)}
    return {"trigger": "model_decision", "description": rule.description}


def _rule_change(rule: RuleSpec) -> PlannedChange:
    return PlannedChange(
        path=f"{_RULES_DIR}/{rule.id}.md",
        action=ChangeAction.UPDATE,
        content=frontmatter_document(_rule_meta(rule), rule.body).encode(),
        reason="rule",
        owner=_OWNER,
    )


def _agent_change(agent: AgentSpec) -> PlannedChange:
    # tools は出さない: ホスト間の tool 名対応が未確認で、未マップ名でハングする既知不具合がある
    meta: dict[str, object] = {"name": agent.id, "description": agent.description}
    body = agent.instructions
    if agent.read_only:
        meta["commandExecutionPolicy"] = "off"
        body = f"{body.rstrip()}\n\n{_READ_ONLY_NOTE}"
    return PlannedChange(
        path=f"{_AGENTS_DIR}/{agent.id}.md",
        action=ChangeAction.UPDATE,
        content=frontmatter_document(meta, body).encode(),
        reason="agent",
        owner=_OWNER,
    )


def _parse_frontmatter(content: bytes | None) -> dict[str, object]:
    text = (content or b"").decode(errors="replace")
    if not text.startswith("---\n"):
        return {}
    header, sep, _ = text[4:].partition("\n---\n")
    if not sep:
        return {}
    try:
        meta = yaml.safe_load(header)
    except yaml.YAMLError:
        return {}
    return meta if isinstance(meta, dict) else {}


def _error(code: str, message: str, path: str) -> Diagnostic:
    return Diagnostic(DiagnosticLevel.ERROR, code, message, path)


def _lint_rule(change: PlannedChange) -> list[Diagnostic]:
    meta = _parse_frontmatter(change.content)
    trigger = meta.get("trigger")
    problem: str | None = None
    if trigger not in _TRIGGERS:
        problem = f"trigger is missing or invalid: {trigger!r}"
    elif trigger == "glob" and not meta.get("globs"):
        problem = "trigger glob requires globs"
    elif trigger == "model_decision" and not meta.get("description"):
        problem = "trigger model_decision requires description"
    diagnostics = [_error("AGY_RULE_TRIGGER", problem, change.path)] if problem else []
    if len(change.content or b"") > _RULE_MAX_BYTES:
        diagnostics.append(
            _error("AGY_RULE_TOO_LARGE", f"rule exceeds {_RULE_MAX_BYTES} bytes", change.path)
        )
    return diagnostics


def _lint_skill(change: PlannedChange) -> list[Diagnostic]:
    extra = sorted(set(_parse_frontmatter(change.content)) - _SKILL_KEYS)
    if not extra:
        return []
    return [_error("SHARED_SKILL_EXTRA_KEY", f"unexpected keys: {', '.join(extra)}", change.path)]


def _lint_agent(change: PlannedChange) -> list[Diagnostic]:
    meta = _parse_frontmatter(change.content)
    missing = [key for key in ("name", "description") if not meta.get(key)]
    if not missing:
        return []
    return [_error("AGY_AGENT_FIELD", f"missing keys: {', '.join(missing)}", change.path)]


def _lint_change(change: PlannedChange) -> list[Diagnostic]:
    path = PurePosixPath(change.path)
    if path.suffix == ".md" and str(path.parent) == _RULES_DIR:
        return _lint_rule(change)
    if path.suffix == ".md" and str(path.parent) == _AGENTS_DIR:
        return _lint_agent(change)
    if path.name == "SKILL.md" and str(path.parent.parent) in _SKILL_DIRS:
        return _lint_skill(change)
    return []


class AntigravityHostAdapter:
    id = HostId.ANTIGRAVITY

    def probe(self) -> RuntimeCapabilityReport:
        report = probe_cli("antigravity", _PROBE, policy_blocked=True)
        return report if report.policy_blocked else replace(report, policy_blocked=True)

    def render(self, spec: CanonicalSpec, ctx: RenderContext) -> GeneratedPlan:
        # GEMINI.md は AGENTS.md との優先順位が未定義のため生成しない（ADR-0001）
        changes = [agents_md_change(spec, owner=_OWNER)]
        for skill in spec.skills:
            changes.extend(shared_skill_changes(skill, owner=_OWNER))
        changes.extend(_rule_change(rule) for rule in spec.rules)
        changes.extend(_agent_change(agent) for agent in spec.agents)
        return GeneratedPlan(
            host=self.id,
            changes=tuple(changes),
            diagnostics=(),
            capabilities=_CAPABILITIES,
        )

    def lint(self, plan: GeneratedPlan) -> tuple[Diagnostic, ...]:
        return tuple(d for change in plan.changes for d in _lint_change(change))

    def discover(self, workspace: Path) -> DiscoveryReport:
        found: dict[str, list[str]] = {}
        for base in _SKILL_DIRS:
            for skill_md in sorted((workspace / base).glob("*/SKILL.md")):
                rel = skill_md.relative_to(workspace).as_posix()
                found.setdefault(skill_md.parent.name, []).append(rel)
        skills: Mapping[str, tuple[str, ...]] = {k: tuple(v) for k, v in found.items()}
        collisions = tuple(name for name, paths in skills.items() if len(paths) > 1)
        return DiscoveryReport(host=self.id, skills=skills, collisions=collisions)
