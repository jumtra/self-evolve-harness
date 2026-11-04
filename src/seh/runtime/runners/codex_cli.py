"""Codex CLI Runner（`codex exec --json`）。フラグと挙動は ADR-0002 の Codex 節が正。"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path

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

# danger-full-access と承認バイパスは評価環境の隔離を壊すため許可しない
_ALLOWED_SANDBOXES = ("read-only", "workspace-write")
# 認証エラーの終了コード・文言は未確認（ADR-0002）。疑い止まりにするため緩い語で拾う
_AUTH_MARKERS = ("login", "auth", "api key", "401")
_TERMINAL_FAILURES = {"turn.failed": "TURN_FAILED", "error": "CODEX_ERROR"}


class CodexCliRunner(BaseCliRunner):
    host = "codex"
    command = "codex"

    def __init__(
        self,
        *,
        artifacts: ArtifactStore | None = None,
        output_schema_path: Path | None = None,
        sandbox: str = "workspace-write",
    ) -> None:
        if sandbox not in _ALLOWED_SANDBOXES:
            raise ValueError(f"sandbox must be one of {_ALLOWED_SANDBOXES}: {sandbox!r}")
        super().__init__(artifacts=artifacts)
        self._output_schema_path = output_schema_path
        self._sandbox = sandbox

    def build_invocation(self, prompt: str, context: RunContext) -> Invocation:
        argv = [
            self.command,
            "exec",
            "--json",
            "-C",
            str(context.cwd),
            "-s",
            self._sandbox,
            "--skip-git-repo-check",
        ]
        if self._output_schema_path is not None:
            argv += ["--output-schema", str(self._output_schema_path)]
        argv.append("-")
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
        if exit_code not in (0, None) and _looks_like_auth_error(stderr):
            return TerminalDecision(TerminalState.BLOCKED_AUTH, "AUTH_SUSPECTED", None)
        terminal = next(
            (
                e
                for e in reversed(events)
                if e.get("type") == "turn.completed" or e.get("type") in _TERMINAL_FAILURES
            ),
            None,
        )
        if terminal is None:
            return TerminalDecision(TerminalState.INVALID_OUTPUT, "NO_TERMINAL_EVENT", None)
        failure_code = _TERMINAL_FAILURES.get(str(terminal.get("type")))
        if failure_code is not None:
            return TerminalDecision(TerminalState.FAILED, failure_code, None)

        final = _final_response(events)
        if self._output_schema_path is None:
            return TerminalDecision(TerminalState.SUCCESS, None, final)
        try:
            structured = json.loads(final) if final is not None else None
        except json.JSONDecodeError:
            structured = None
        if structured is None:
            return TerminalDecision(
                TerminalState.INVALID_OUTPUT, "STRUCTURED_OUTPUT_INVALID", final
            )
        return TerminalDecision(TerminalState.SUCCESS, None, final, structured_output=structured)

    def normalize_usage(self, events: Sequence[Mapping[str, object]]) -> Usage | None:
        completed = next((e for e in reversed(events) if e.get("type") == "turn.completed"), None)
        raw = completed.get("usage") if completed else None
        if not isinstance(raw, dict):
            return None
        return Usage(
            input_tokens=_int_or_none(raw.get("input_tokens")),
            output_tokens=_int_or_none(raw.get("output_tokens")),
            cost_usd=None,
            raw=raw,
        )

    def probe_spec(self) -> ProbeSpec:
        return ProbeSpec(
            command=self.command,
            help_args=("exec", "--help"),
            required_flags={
                "json": ("--json",),
                "output_schema": ("--output-schema",),
                "sandbox": ("--sandbox",),
                "cd": ("--cd",),
            },
        )


def _looks_like_auth_error(stderr: bytes) -> bool:
    text = stderr.decode(errors="replace").lower()
    return any(marker in text for marker in _AUTH_MARKERS)


def _int_or_none(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _final_response(events: Sequence[Mapping[str, object]]) -> str | None:
    for event in reversed(events):
        item = event.get("item")
        if event.get("type") != "item.completed" or not isinstance(item, dict):
            continue
        if not str(item.get("type", "")).startswith("agent_message"):
            continue
        for key in ("text", "content"):
            value = item.get(key)
            if isinstance(value, str):
                return value
        # 最後の agent_message の形式が想定外なら、古い発話で推測せず None にする
        return None
    return None


def register(registry: RunnerRegistry) -> None:
    registry.register(CodexCliRunner())
