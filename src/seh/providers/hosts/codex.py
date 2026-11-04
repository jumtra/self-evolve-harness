from __future__ import annotations

import tomllib
from collections.abc import Mapping
from pathlib import Path

import tomli_w
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
from seh.providers.hosts.common import SHARED_SKILLS_DIR, agents_md_change, shared_skill_changes
from seh.providers.hosts.hooks_map import render_hooks
from seh.providers.hosts.permissions_map import map_permissions
from seh.runtime.cli_capability import ProbeSpec, probe_cli

OWNER = "host:codex"
AGENTS_MD_PATH = "AGENTS.md"
AGENTS_MD_MAX_BYTES = 32 * 1024
AGENT_DIR = ".codex/agents"
READ_ONLY_NOTE = "ファイルを編集・作成・削除してはならない（読み取り専用）。"
REQUIRED_AGENT_KEYS = ("name", "description", "developer_instructions")
# agent ファイルでは無効（ADR-0001）。書いても効かないまま安全だと誤認させるため ERROR にする
INEFFECTIVE_AGENT_KEYS = ("sandbox_mode", "approval_policy")
SHARED_SKILL_KEYS = frozenset({"name", "description"})

_PROBE = ProbeSpec(
    command="codex",
    help_args=("exec", "--help"),
    required_flags={
        "json": ("--json",),
        "output_schema": ("--output-schema",),
        "sandbox": ("--sandbox",),
        "cd": ("--cd",),
    },
)

_CAPABILITIES = (
    HostCapability("instructions", CapabilityLevel.NATIVE, "AGENTS.md を常時指示として読む"),
    HostCapability("skills", CapabilityLevel.NATIVE, ".agents/skills を読む"),
    HostCapability("agents", CapabilityLevel.ADAPTED, ".codex/agents/<id>.toml に変換する"),
    HostCapability(
        "agents.read_only",
        CapabilityLevel.ADAPTED,
        "developer_instructions のみで強制力なし。Managed 時 --sandbox read-only と CI で補完",
    ),
    HostCapability(
        "rules.path_scoped", CapabilityLevel.CI_ONLY, "path-scoped な指示の仕組みが無い"
    ),
    HostCapability(
        "hooks.pre_tool_use",
        CapabilityLevel.ADAPTED,
        ".codex/hooks.json は trust 済みでないと実行されない。生成は後続タスク",
    ),
    HostCapability(
        "permissions", CapabilityLevel.ADAPTED, ".codex/rules で表現する。生成は後続タスク"
    ),
)


def _agent_change(agent: AgentSpec) -> PlannedChange:
    instructions = agent.instructions.rstrip()
    if agent.read_only:
        instructions = f"{instructions}\n\n{READ_ONLY_NOTE}"
    data: dict[str, object] = {
        "name": agent.id,
        "description": agent.description,
        "developer_instructions": f"{instructions}\n",
    }
    if agent.effort:
        data["model_reasoning_effort"] = agent.effort
    return PlannedChange(
        path=f"{AGENT_DIR}/{agent.id}.toml",
        action=ChangeAction.UPDATE,
        content=tomli_w.dumps(data).encode(),
        reason="agent",
        owner=OWNER,
    )


def _agents_md_size_error(change: PlannedChange) -> Diagnostic | None:
    if change.content is None or len(change.content) <= AGENTS_MD_MAX_BYTES:
        return None
    return Diagnostic(
        DiagnosticLevel.ERROR,
        "AGENTS_MD_TOO_LARGE",
        f"AGENTS.md exceeds Codex default limit of {AGENTS_MD_MAX_BYTES} bytes",
        change.path,
    )


def _error(code: str, message: str, path: str) -> Diagnostic:
    return Diagnostic(DiagnosticLevel.ERROR, code, message, path)


def _lint_agent(change: PlannedChange) -> list[Diagnostic]:
    try:
        data = tomllib.loads((change.content or b"").decode())
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as exc:
        return [_error("CODEX_AGENT_INVALID_TOML", str(exc), change.path)]
    found = [
        _error("CODEX_AGENT_MISSING_KEY", f"missing required key: {key}", change.path)
        for key in REQUIRED_AGENT_KEYS
        if key not in data
    ]
    found += [
        _error("CODEX_AGENT_INEFFECTIVE_KEY", f"{key} is ignored in agent files", change.path)
        for key in INEFFECTIVE_AGENT_KEYS
        if key in data
    ]
    return found


def _frontmatter(text: str) -> Mapping[str, object] | None:
    if not text.startswith("---\n"):
        return None
    end = text.find("\n---", 4)
    if end < 0:
        return None
    try:
        meta = yaml.safe_load(text[4:end])
    except yaml.YAMLError:
        return None
    return meta if isinstance(meta, dict) else None


def _lint_shared_skill(change: PlannedChange) -> list[Diagnostic]:
    meta = _frontmatter((change.content or b"").decode(errors="replace"))
    if meta is None:
        return [_error("SHARED_SKILL_NO_FRONTMATTER", "frontmatter not found", change.path)]
    return [
        _error("SHARED_SKILL_EXTRA_KEY", f"unexpected key: {key}", change.path)
        for key in meta
        if key not in SHARED_SKILL_KEYS
    ]


def _is_agent(path: str) -> bool:
    return path.startswith(f"{AGENT_DIR}/") and path.endswith(".toml")


def _is_shared_skill(path: str) -> bool:
    parts = path.split("/")
    return path.startswith(f"{SHARED_SKILLS_DIR}/") and len(parts) == 4 and parts[3] == "SKILL.md"


class CodexHostAdapter:
    id = HostId.CODEX

    def probe(self) -> RuntimeCapabilityReport:
        return probe_cli("codex", _PROBE)

    def render(self, spec: CanonicalSpec, ctx: RenderContext) -> GeneratedPlan:
        agents_md = agents_md_change(spec, owner=OWNER)
        changes = [agents_md]
        for skill in spec.skills:
            changes += shared_skill_changes(skill, owner=OWNER)
        changes += [_agent_change(agent) for agent in spec.agents]
        size_error = _agents_md_size_error(agents_md)
        permission_mapping = map_permissions(self.id, spec.permissions)
        changes.extend(render_hooks(self.id, permission_mapping.permissions))
        return GeneratedPlan(
            host=self.id,
            changes=tuple(changes),
            diagnostics=((size_error,) if size_error else ()) + permission_mapping.diagnostics,
            capabilities=_CAPABILITIES,
        )

    def lint(self, plan: GeneratedPlan) -> tuple[Diagnostic, ...]:
        found: list[Diagnostic] = []
        for change in plan.changes:
            if change.path == AGENTS_MD_PATH:
                found += [e] if (e := _agents_md_size_error(change)) else []
            elif _is_agent(change.path):
                found += _lint_agent(change)
            elif _is_shared_skill(change.path):
                found += _lint_shared_skill(change)
        return tuple(found)

    def discover(self, workspace: Path) -> DiscoveryReport:
        skills: dict[str, list[str]] = {}
        for path in sorted((workspace / SHARED_SKILLS_DIR).glob("*/SKILL.md")):
            meta = _frontmatter(path.read_text(encoding="utf-8", errors="replace"))
            name = str(meta["name"]) if meta and "name" in meta else path.parent.name
            skills.setdefault(name, []).append(path.relative_to(workspace).as_posix())
        return DiscoveryReport(
            host=self.id,
            skills={name: tuple(paths) for name, paths in skills.items()},
            collisions=tuple(name for name, paths in skills.items() if len(paths) > 1),
        )
