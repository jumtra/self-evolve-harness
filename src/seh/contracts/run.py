from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from seh.contracts.host import CapabilityLevel


class TerminalState(StrEnum):
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    BLOCKED_AUTH = "BLOCKED_AUTH"
    POLICY_BLOCKED = "POLICY_BLOCKED"
    UNSUPPORTED = "UNSUPPORTED"
    INVALID_OUTPUT = "INVALID_OUTPUT"
    TIMED_OUT = "TIMED_OUT"
    CANCELLED = "CANCELLED"


@dataclass(frozen=True)
class Usage:
    """None は UNKNOWN（計測不能）。0 は「使わなかった」で別物。"""

    input_tokens: int | None
    output_tokens: int | None
    cost_usd: float | None
    raw: Mapping[str, object] | None


@dataclass(frozen=True)
class RunContext:
    worktree: Path
    cwd: Path
    deadline_seconds: int
    env_allowlist: tuple[str, ...]
    session_policy: str = "fresh"
    permissions_profile: str = "default"
    hooks_enabled: bool = True


@dataclass(frozen=True)
class RunResult:
    run_id: str
    host: str
    terminal_state: TerminalState
    exit_code: int | None
    final_response: str | None
    event_log_digest: str | None
    evidence_refs: tuple[str, ...]
    usage: Usage | None
    error_code: str | None
    structured_output: object | None = None
    permission_denials: tuple[Mapping[str, object], ...] = ()


@dataclass(frozen=True)
class RuntimeCapabilityReport:
    host: str
    installed: bool
    version: str | None
    authenticated: bool | None
    capabilities: Mapping[str, CapabilityLevel]
    policy_blocked: bool
    notes: tuple[str, ...]


class CliAgentRunner(Protocol):
    host: str

    def probe(self) -> RuntimeCapabilityReport: ...

    async def run_once(self, prompt: str, context: RunContext) -> RunResult: ...

    async def cancel(self, run_id: str) -> None: ...
