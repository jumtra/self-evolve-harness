"""Antigravity（AGY）CLI（`agy -p`）Runner。仕様の正は ADR-0002。"""

from __future__ import annotations

import json
import uuid
from collections.abc import Mapping, Sequence
from typing import Literal

from seh.artifacts import ArtifactStore
from seh.config import Config
from seh.contracts import (
    RunContext,
    RunResult,
    RuntimeCapabilityReport,
    TerminalState,
    Usage,
)
from seh.redaction import mask_text
from seh.runtime.agent_runner import RunnerRegistry
from seh.runtime.cli_capability import ProbeSpec, probe_cli
from seh.runtime.runners.base import (
    BaseCliRunner,
    InvalidEventStream,
    Invocation,
    TerminalDecision,
)

_POLICY_ERROR = "AGY_THIRD_PARTY_WRAPPING_NOT_PERMITTED"
_CANCELLED_STATUSES = frozenset({"CANCELED", "INTERRUPTED"})
_FAILED_STATUSES = frozenset({"ERROR", "INVALID"})
_NON_TERMINAL_STATUSES = frozenset({"WAITING", "RUNNING"})


def _result_event(events: Sequence[Mapping[str, object]]) -> Mapping[str, object] | None:
    return next((e for e in reversed(events) if e.get("type") == "result"), None)


def _soft_denials(stderr: bytes) -> tuple[Mapping[str, object], ...]:
    # AGY は権限拒否後も実行を続けるため、stderr の通知を拒否として拾う
    lines = (line.strip() for line in stderr.decode(errors="replace").splitlines())
    return tuple(
        {"source": "stderr", "line": mask_text(line)}
        for line in lines
        if "permission" in line.lower() and "denied" in line.lower()
    )


def _is_auth_failure(result: Mapping[str, object]) -> bool:
    return "authentication required" in str(result.get("error", "")).lower()


class AntigravityCliRunner(BaseCliRunner):
    host = "antigravity"
    command = "agy"

    def __init__(
        self,
        *,
        managed_cli: Literal["disabled", "enabled"] = "disabled",
        artifacts: ArtifactStore | None = None,
        json_schema: Mapping[str, object] | None = None,
    ) -> None:
        super().__init__(artifacts=artifacts)
        self._managed_cli = managed_cli
        self._json_schema = json_schema

    @classmethod
    def from_config(
        cls, config: Config, *, artifacts: ArtifactStore | None = None, **kw: object
    ) -> AntigravityCliRunner:
        schema = kw.get("json_schema")
        return cls(
            managed_cli=config.hosts.antigravity_managed_cli,
            artifacts=artifacts,
            json_schema=schema if isinstance(schema, Mapping) else None,
        )

    async def run_once(self, prompt: str, context: RunContext) -> RunResult:
        if self._managed_cli == "disabled":
            # 利用条件が確認されるまでプロセスを起動せず、他ホストへの振替もしない（FR-099）
            return self._result(uuid.uuid4().hex, TerminalState.POLICY_BLOCKED, _POLICY_ERROR)
        return await super().run_once(prompt, context)

    def build_invocation(self, prompt: str, context: RunContext) -> Invocation:
        argv = [self.command, "-p", "--output-format", "stream-json"]
        if self._json_schema is not None:
            argv += ["--json-schema", json.dumps(self._json_schema)]
        return Invocation(argv=tuple(argv), stdin=prompt.encode())

    def parse_events(self, stdout: bytes) -> list[Mapping[str, object]]:
        events: list[Mapping[str, object]] = []
        for line in stdout.decode(errors="replace").splitlines():
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError as exc:
                raise InvalidEventStream(str(exc)) from exc
            if not isinstance(event, dict):
                raise InvalidEventStream("event is not an object")
            events.append(event)
        return events

    def detect_terminal(
        self, events: Sequence[Mapping[str, object]], exit_code: int | None, stderr: bytes
    ) -> TerminalDecision:
        result = _result_event(events)
        if result is None:
            return TerminalDecision(TerminalState.INVALID_OUTPUT, "NO_TERMINAL_EVENT", None)
        text = result.get("result")
        final_response = text if isinstance(text, str) else None
        structured = result.get("structured_output")
        denials = _soft_denials(stderr)

        def decision(state: TerminalState, code: str | None) -> TerminalDecision:
            return TerminalDecision(state, code, final_response, structured, denials)

        status = result.get("status")
        if status == "SUCCESS":
            return decision(TerminalState.SUCCESS, None)
        if _is_auth_failure(result):
            return decision(TerminalState.BLOCKED_AUTH, "AUTH_FAILED")
        if status in _CANCELLED_STATUSES:
            return decision(TerminalState.CANCELLED, "CANCELLED")
        if status in _NON_TERMINAL_STATUSES:
            return decision(TerminalState.INVALID_OUTPUT, "NOT_TERMINAL")
        if status in _FAILED_STATUSES:
            return decision(TerminalState.FAILED, str(status))
        return decision(TerminalState.FAILED, "RESULT_ERROR")

    def normalize_usage(self, events: Sequence[Mapping[str, object]]) -> Usage | None:
        result = _result_event(events)
        usage = result.get("usage") if result is not None else None
        if not isinstance(usage, dict):
            return None
        input_tokens = usage.get("input_tokens")
        output_tokens = usage.get("output_tokens")
        return Usage(
            input_tokens if isinstance(input_tokens, int) else 0,
            output_tokens if isinstance(output_tokens, int) else 0,
            None,
            {},
        )

    def probe_spec(self) -> ProbeSpec:
        return ProbeSpec(
            command=self.command,
            required_flags={
                "print": ("-p",),
                "output_format": ("--output-format",),
                "json_schema": ("--json-schema",),
            },
        )

    def probe(self) -> RuntimeCapabilityReport:
        return probe_cli(
            self.host, self.probe_spec(), policy_blocked=self._managed_cli == "disabled"
        )


def register(registry: RunnerRegistry, *, managed_cli: str = "disabled") -> None:
    registry.register(
        AntigravityCliRunner(managed_cli="enabled" if managed_cli == "enabled" else "disabled")
    )
