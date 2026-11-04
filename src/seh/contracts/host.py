from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from seh.contracts.run import RuntimeCapabilityReport


class HostId(StrEnum):
    CLAUDE = "claude"
    ANTIGRAVITY = "antigravity"
    CODEX = "codex"
    OPENCODE = "opencode"


class CapabilityLevel(StrEnum):
    NATIVE = "NATIVE"
    ADAPTED = "ADAPTED"
    CI_ONLY = "CI_ONLY"
    UNSUPPORTED = "UNSUPPORTED"
    UNVERIFIED = "UNVERIFIED"


class HostVerdict(StrEnum):
    FULL = "FULL"
    PARTIAL = "PARTIAL"
    BLOCKED = "BLOCKED"
    UNSUPPORTED = "UNSUPPORTED"


@dataclass(frozen=True)
class HostCapability:
    feature: str
    level: CapabilityLevel
    reason: str
    evidence: tuple[str, ...] = ()


_SKILL_ID = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


@dataclass(frozen=True)
class SkillSpec:
    id: str
    description: str
    body: str
    references: Mapping[str, str] = field(default_factory=dict)
    claude_frontmatter: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not 1 <= len(self.id) <= 64 or not _SKILL_ID.fullmatch(self.id):
            raise ValueError(f"invalid skill id: {self.id!r}")
        if not 1 <= len(self.description) <= 1024:
            raise ValueError("skill description must be 1..1024 characters")


@dataclass(frozen=True)
class AgentSpec:
    id: str
    description: str
    instructions: str
    tools: tuple[str, ...]
    read_only: bool
    model: str | None = None
    effort: str | None = None


@dataclass(frozen=True)
class RuleSpec:
    id: str
    description: str
    body: str
    globs: tuple[str, ...] = ()
    always: bool = False


@dataclass(frozen=True)
class CanonicalSpec:
    instructions: str
    skills: tuple[SkillSpec, ...]
    agents: tuple[AgentSpec, ...]
    rules: tuple[RuleSpec, ...]
    permissions: Mapping[str, str] = field(default_factory=dict)


class ChangeAction(StrEnum):
    CREATE = "CREATE"
    UPDATE = "UPDATE"
    DELETE = "DELETE"
    LINK = "LINK"
    KEEP = "KEEP"


@dataclass(frozen=True)
class PlannedChange:
    path: str
    action: ChangeAction
    content: bytes | None
    reason: str
    owner: str


class DiagnosticLevel(StrEnum):
    ERROR = "ERROR"
    WARN = "WARN"
    INFO = "INFO"


@dataclass(frozen=True)
class Diagnostic:
    level: DiagnosticLevel
    code: str
    message: str
    path: str | None = None


@dataclass(frozen=True)
class GeneratedPlan:
    host: HostId
    changes: tuple[PlannedChange, ...]
    diagnostics: tuple[Diagnostic, ...]
    capabilities: tuple[HostCapability, ...]


@dataclass(frozen=True)
class DiscoveryReport:
    host: HostId
    skills: Mapping[str, tuple[str, ...]]
    collisions: tuple[str, ...]


@dataclass(frozen=True)
class RenderContext:
    root: Path
    enabled_hosts: tuple[HostId, ...]
    project_name: str


class HostAdapter(Protocol):
    id: HostId

    def probe(self) -> RuntimeCapabilityReport: ...

    def render(self, spec: CanonicalSpec, ctx: RenderContext) -> GeneratedPlan: ...

    def lint(self, plan: GeneratedPlan) -> tuple[Diagnostic, ...]: ...

    def discover(self, workspace: Path) -> DiscoveryReport: ...
