from __future__ import annotations

import os
import re
from collections.abc import Mapping
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
    RuntimeCapabilityReport,
)
from seh.providers.hosts.common import (
    SHARED_SKILLS_DIR,
    agents_md_change,
    frontmatter_document,
    shared_skill_changes,
)
from seh.runtime.cli_capability import ProbeSpec, probe_cli

_OWNER = "host:opencode"
_AGENTS_DIR = ".opencode/agents"
_SKILL_NAME = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
_MODES = frozenset({"primary", "subagent", "all"})
_DISABLE_CLAUDE_ENV = "OPENCODE_DISABLE_CLAUDE_CODE_SKILLS"
_DISABLE_EXTERNAL_ENV = "OPENCODE_DISABLE_EXTERNAL_SKILLS"
# 探索順。ADR-0005 の表に対応する
_CLAUDE_SKILLS = ".claude/skills"
_SKILL_DIRS = (".opencode/skills", _CLAUDE_SKILLS, SHARED_SKILLS_DIR)

_PROBE = ProbeSpec(
    command="opencode",
    help_args=("run", "--help"),
    required_flags={"format": ("--format",), "dir": ("--dir",), "agent": ("--agent",)},
)

_COLLISION_MESSAGE = (
    "OpenCode は .claude/skills と .agents/skills の両方を探索するため同名 Skill が二重に見える。"
    "Managed 実行は Runner が OPENCODE_DISABLE_CLAUDE_CODE_SKILLS=1 で抑止、"
    "Native 利用時は利用者がシェルで同変数を設定すること"
)


def _capability(feature: str, level: CapabilityLevel, reason: str) -> HostCapability:
    return HostCapability(feature=feature, level=level, reason=reason)


def _capabilities(with_claude: bool) -> tuple[HostCapability, ...]:
    skills = (
        _capability(
            "skills",
            CapabilityLevel.ADAPTED,
            "COLLISION: .claude/skills と .agents/skills の両方を探索する（ADR-0005）",
        )
        if with_claude
        else _capability("skills", CapabilityLevel.NATIVE, ".agents/skills を読む")
    )
    return (
        _capability("instructions", CapabilityLevel.NATIVE, "AGENTS.md を読む"),
        skills,
        _capability("agents", CapabilityLevel.NATIVE, ".opencode/agents/<name>.md"),
        _capability("agents.read_only", CapabilityLevel.NATIVE, "permission で edit/bash を deny"),
        _capability(
            "rules.path_scoped", CapabilityLevel.UNSUPPORTED, "path-scoped 指示の手段が未確認"
        ),
        _capability(
            "hooks.pre_tool_use",
            CapabilityLevel.NATIVE,
            "plugin で実現。subagent への効き方は UNVERIFIED。生成は後続タスク（T49）",
        ),
        _capability("permissions", CapabilityLevel.NATIVE, "permission の allow/ask/deny"),
    )


def _agent_change(agent: AgentSpec) -> PlannedChange:
    permission = (
        {"edit": "deny", "bash": "deny"} if agent.read_only else {"edit": "allow", "bash": "ask"}
    )
    # model は出さない: ホスト間のモデル名対応が未確認
    meta: dict[str, object] = {
        "description": agent.description,
        "mode": "subagent",
        "permission": permission,
    }
    return PlannedChange(
        path=f"{_AGENTS_DIR}/{agent.id}.md",
        action=ChangeAction.UPDATE,
        content=frontmatter_document(meta, agent.instructions).encode(),
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


def _lint_skill(change: PlannedChange) -> list[Diagnostic]:
    meta = _parse_frontmatter(change.content)
    name = meta.get("name")
    directory = PurePosixPath(change.path).parent.name
    diagnostics: list[Diagnostic] = []
    if (
        not isinstance(name, str)
        or not 1 <= len(name) <= 64
        or not _SKILL_NAME.fullmatch(name)
        or name != directory
    ):
        diagnostics.append(
            _error(
                "OPENCODE_SKILL_NAME",
                f"name must match {_SKILL_NAME.pattern}, be 1..64 chars and equal "
                f"the directory name {directory!r}: {name!r}",
                change.path,
            )
        )
    description = meta.get("description")
    if not isinstance(description, str) or not 1 <= len(description) <= 1024:
        diagnostics.append(
            _error(
                "OPENCODE_SKILL_DESCRIPTION",
                "description must be 1..1024 characters",
                change.path,
            )
        )
    return diagnostics


def _lint_agent(change: PlannedChange) -> list[Diagnostic]:
    meta = _parse_frontmatter(change.content)
    problems: list[str] = []
    if not meta.get("description"):
        problems.append("description is missing")
    if meta.get("mode") not in _MODES:
        problems.append(f"mode must be one of {sorted(_MODES)}: {meta.get('mode')!r}")
    diagnostics = [_error("OPENCODE_AGENT_FIELD", p, change.path) for p in problems]
    permission = meta.get("permission")
    # bash を deny する agent は read_only として生成されたもの。edit も deny でなければ矛盾
    if (
        isinstance(permission, dict)
        and permission.get("bash") == "deny"
        and permission.get("edit") != "deny"
    ):
        diagnostics.append(
            _error(
                "OPENCODE_READ_ONLY_PERMISSION",
                "read-only agent must set permission.edit to deny",
                change.path,
            )
        )
    return diagnostics


def _lint_change(change: PlannedChange) -> list[Diagnostic]:
    path = PurePosixPath(change.path)
    if path.name == "SKILL.md" and str(path.parent.parent) == SHARED_SKILLS_DIR:
        return _lint_skill(change)
    if path.suffix == ".md" and str(path.parent) == _AGENTS_DIR:
        return _lint_agent(change)
    return []


def _is_truthy(value: str | None) -> bool:
    return value is not None and value.strip().lower() not in ("", "0", "false")


def _active_skill_dirs(env: Mapping[str, str]) -> tuple[str, ...]:
    if _is_truthy(env.get(_DISABLE_EXTERNAL_ENV)):
        return tuple(d for d in _SKILL_DIRS if d not in (_CLAUDE_SKILLS, SHARED_SKILLS_DIR))
    if _is_truthy(env.get(_DISABLE_CLAUDE_ENV)):
        return tuple(d for d in _SKILL_DIRS if d != _CLAUDE_SKILLS)
    return _SKILL_DIRS


class OpenCodeHostAdapter:
    id = HostId.OPENCODE

    def probe(self) -> RuntimeCapabilityReport:
        return probe_cli("opencode", _PROBE)

    def render(self, spec: CanonicalSpec, ctx: RenderContext) -> GeneratedPlan:
        # Rule は生成しない: path-scoped 指示の手段が未確認（ADR-0001）
        changes = [agents_md_change(spec, owner=_OWNER)]
        for skill in spec.skills:
            changes.extend(shared_skill_changes(skill, owner=_OWNER))
        changes.extend(_agent_change(agent) for agent in spec.agents)
        with_claude = HostId.CLAUDE in ctx.enabled_hosts
        diagnostics = (
            (Diagnostic(DiagnosticLevel.WARN, "SKILL_DISCOVERY_COLLISION", _COLLISION_MESSAGE),)
            if with_claude
            else ()
        )
        return GeneratedPlan(
            host=self.id,
            changes=tuple(changes),
            diagnostics=diagnostics,
            capabilities=_capabilities(with_claude),
        )

    def lint(self, plan: GeneratedPlan) -> tuple[Diagnostic, ...]:
        return tuple(d for change in plan.changes for d in _lint_change(change))

    def discover(self, workspace: Path, *, env: Mapping[str, str] | None = None) -> DiscoveryReport:
        active = _active_skill_dirs(os.environ if env is None else env)
        found: dict[str, list[str]] = {}
        for base in active:
            for skill_md in sorted((workspace / base).glob("*/SKILL.md")):
                rel = skill_md.relative_to(workspace).as_posix()
                found.setdefault(skill_md.parent.name, []).append(rel)
        skills: Mapping[str, tuple[str, ...]] = {k: tuple(v) for k, v in found.items()}
        collisions = tuple(name for name, paths in skills.items() if len(paths) > 1)
        return DiscoveryReport(host=self.id, skills=skills, collisions=collisions)
