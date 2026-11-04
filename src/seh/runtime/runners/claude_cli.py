"""Claude Code の非対話 CLI（`claude -p`）Runner。仕様の正は ADR-0002。"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence

from seh.artifacts import ArtifactStore
from seh.contracts import RunContext, TerminalState, Usage
from seh.runtime.agent_runner import RunnerRegistry
from seh.runtime.cli_capability import ProbeSpec
from seh.runtime.runners.base import (
    BaseCliRunner,
    InvalidEventStream,
    Invocation,
    TerminalDecision,
)

_FAILED_SUBTYPES = frozenset(
    {
        "error_max_turns",
        "error_max_budget_usd",
        "error_during_execution",
        "error_max_structured_output_retries",
    }
)
_AUTH_MARKERS = ("authentication", "not logged in", "invalid api key")


def _result_event(events: Sequence[Mapping[str, object]]) -> Mapping[str, object] | None:
    return next((e for e in reversed(events) if e.get("type") == "result"), None)


def _mentions_auth(value: object) -> bool:
    return isinstance(value, str) and any(m in value.lower() for m in _AUTH_MARKERS)


def _is_auth_failure(events: Sequence[Mapping[str, object]], result: Mapping[str, object]) -> bool:
    retried = any(
        e.get("type") == "system"
        and e.get("subtype") == "api_retry"
        and "authentication" in str(e.get("error", "")).lower()
        for e in events
    )
    return retried or _mentions_auth(result.get("result")) or _mentions_auth(result.get("error"))


def _as_int(value: object) -> int:
    return value if isinstance(value, int) else 0


class ClaudeCliRunner(BaseCliRunner):
    host = "claude"
    command = "claude"

    def __init__(
        self,
        *,
        artifacts: ArtifactStore | None = None,
        json_schema: Mapping[str, object] | None = None,
        allowed_tools: Sequence[str] = (),
        permission_mode: str | None = None,
        max_budget_usd: float | None = None,
    ) -> None:
        super().__init__(artifacts=artifacts)
        self._json_schema = json_schema
        self._allowed_tools = tuple(allowed_tools)
        self._permission_mode = permission_mode
        self._max_budget_usd = max_budget_usd

    def build_invocation(self, prompt: str, context: RunContext) -> Invocation:
        # --bare は Skill/Hook を読まないため使わない
        argv = [
            self.command,
            "-p",
            "--output-format",
            "stream-json",
            "--verbose",
            "--permission-prompts",
            "none",
        ]
        if self._json_schema is not None:
            argv += ["--json-schema", json.dumps(self._json_schema)]
        if self._allowed_tools:
            argv += ["--allowedTools", *self._allowed_tools]
        if self._permission_mode is not None:
            argv += ["--permission-mode", self._permission_mode]
        if self._max_budget_usd is not None:
            argv += ["--max-budget-usd", str(self._max_budget_usd)]
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
        raw_denials = result.get("permission_denials")
        denials = (
            tuple(d for d in raw_denials if isinstance(d, dict))
            if isinstance(raw_denials, list)
            else ()
        )
        structured = result.get("structured_output")

        def decision(state: TerminalState, code: str | None) -> TerminalDecision:
            return TerminalDecision(state, code, final_response, structured, denials)

        subtype = result.get("subtype")
        succeeded = subtype == "success" and result.get("is_error") is False
        if not succeeded and _is_auth_failure(events, result):
            return decision(TerminalState.BLOCKED_AUTH, "AUTH_FAILED")
        if isinstance(subtype, str) and subtype in _FAILED_SUBTYPES:
            return decision(TerminalState.FAILED, subtype.upper())
        if not succeeded:
            return decision(TerminalState.FAILED, "RESULT_ERROR")
        if self._json_schema is not None and structured is None:
            return decision(TerminalState.INVALID_OUTPUT, "STRUCTURED_OUTPUT_MISSING")
        return decision(TerminalState.SUCCESS, None)

    def normalize_usage(self, events: Sequence[Mapping[str, object]]) -> Usage | None:
        result = _result_event(events)
        if result is None:
            return None
        cost = result.get("total_cost_usd")
        cost_usd = float(cost) if isinstance(cost, (int, float)) else None
        model_usage = result.get("modelUsage")
        usage = result.get("usage")
        if isinstance(model_usage, dict) and model_usage:
            per_model = [m for m in model_usage.values() if isinstance(m, dict)]
            input_tokens = sum(_as_int(m.get("inputTokens")) for m in per_model)
            output_tokens = sum(_as_int(m.get("outputTokens")) for m in per_model)
        elif isinstance(usage, dict):
            input_tokens = _as_int(usage.get("input_tokens"))
            output_tokens = _as_int(usage.get("output_tokens"))
        else:
            return None
        raw: dict[str, object] = {"cost_is_estimate": True}
        if isinstance(model_usage, dict):
            raw["modelUsage"] = model_usage
        return Usage(input_tokens, output_tokens, cost_usd, raw)

    def probe_spec(self) -> ProbeSpec:
        return ProbeSpec(
            command=self.command,
            required_flags={
                "print": ("-p",),
                "output_format": ("--output-format",),
                "json_schema": ("--json-schema",),
                "allowed_tools": ("--allowedTools",),
                "permission_prompts": ("--permission-prompts",),
            },
        )


def register(registry: RunnerRegistry) -> None:
    registry.register(ClaudeCliRunner())
