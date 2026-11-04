from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Literal


class RiskRank(StrEnum):
    R0 = "R0"
    R1 = "R1"
    R2 = "R2"


class NodeKind(StrEnum):
    SPLITTER = "splitter"
    WORKER = "worker"
    CODE = "code"
    GATE = "gate"


@dataclass(frozen=True)
class TaskLimits:
    max_parallel: int = 3
    max_attempts_per_unit: int = 3
    max_wall_seconds: int = 1800
    max_seconds_per_unit: int = 600


@dataclass(frozen=True)
class TaskSpec:
    id: str
    goal: str
    acceptance: tuple[str, ...]
    risk: RiskRank
    mode: Literal["native", "managed"]
    limits: TaskLimits = field(default_factory=TaskLimits)
    required_capabilities: tuple[str, ...] = ()


@dataclass(frozen=True)
class WorkUnit:
    node_id: str
    kind: NodeKind
    depends_on: tuple[str, ...]
    inputs: Mapping[str, str]
    outputs_schema: str | None
    write_allowlist: tuple[str, ...]
    checks: tuple[str, ...]
    risk: RiskRank
    prompt: str | None = None
    host: str | None = None


@dataclass(frozen=True)
class Edge:
    from_node: str
    from_output: str
    to_node: str
    to_input: str
