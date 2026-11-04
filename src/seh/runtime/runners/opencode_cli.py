"""OpenCode Runner（`opencode run`）。

イベントスキーマは公式未記載（UNVERIFIED）のため判定は保守的にする。
"""

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

_AUTH_HINTS = ("auth", "login", "api key", "401")


def _part(event: Mapping[str, object]) -> Mapping[str, object]:
    part = event.get("part")
    return part if isinstance(part, dict) else event


def _tool_failed(event: Mapping[str, object]) -> bool:
    if not str(event.get("type", "")).startswith("tool"):
        return False
    state = _part(event).get("state")
    return isinstance(state, dict) and state.get("status") == "error"


def _tokens(part: Mapping[str, object]) -> Mapping[str, object]:
    tokens = part.get("tokens")
    return tokens if isinstance(tokens, dict) else {}


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return value


def _sum(values: Sequence[float | None]) -> float | None:
    if any(v is None for v in values):
        return None
    return sum(v for v in values if v is not None)


class OpenCodeCliRunner(BaseCliRunner):
    host = "opencode"
    command = "opencode"

    def __init__(
        self,
        *,
        artifacts: ArtifactStore | None = None,
        agent: str | None = None,
        auto_approve: bool = False,
    ) -> None:
        super().__init__(artifacts=artifacts)
        self._agent = agent
        self._auto_approve = auto_approve

    def build_invocation(self, prompt: str, context: RunContext) -> Invocation:
        argv = ["opencode", "run", "--format", "json", "--dir", str(context.cwd)]
        if self._agent:
            argv += ["--agent", self._agent]
        # --auto は worktree 隔離を前提に利用者が明示したときだけ付ける（ask でのハング対策）
        if self._auto_approve:
            argv.append("--auto")
        # --pure は seh-guard プラグインを無効にするため付けない（ADR-0003）
        return Invocation(
            argv=tuple(argv),
            stdin=prompt.encode(),
            # Claude Code 用 Skill の二重探索を抑止する（ADR-0005）
            env_extra={"OPENCODE_DISABLE_CLAUDE_CODE_SKILLS": "1"},
        )

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
        stderr_text = stderr.decode(errors="replace").lower()
        if exit_code != 0 and any(hint in stderr_text for hint in _AUTH_HINTS):
            return TerminalDecision(TerminalState.BLOCKED_AUTH, "AUTH_SUSPECTED", None)
        if not events:
            return TerminalDecision(TerminalState.INVALID_OUTPUT, "EMPTY_OUTPUT", None)
        final = self._final_response(events)
        if any(e.get("type") == "error" for e in events):
            return TerminalDecision(TerminalState.FAILED, "OPENCODE_ERROR", final)
        if any(_tool_failed(e) for e in events):
            return TerminalDecision(TerminalState.FAILED, "TOOL_ERROR", final)
        finishes = [e for e in events if e.get("type") == "step_finish"]
        if not finishes or _part(finishes[-1]).get("reason") != "stop":
            return TerminalDecision(TerminalState.INVALID_OUTPUT, "NO_TERMINAL_EVENT", final)
        return TerminalDecision(TerminalState.SUCCESS, None, final)

    @staticmethod
    def _final_response(events: Sequence[Mapping[str, object]]) -> str | None:
        texts = [
            t
            for e in events
            if e.get("type") == "text" and isinstance(t := _part(e).get("text"), str)
        ]
        return "".join(texts) if texts else None

    def normalize_usage(self, events: Sequence[Mapping[str, object]]) -> Usage | None:
        finishes = [_part(e) for e in events if e.get("type") == "step_finish"]
        if not finishes:
            return None
        tokens = [_tokens(p) for p in finishes]
        input_total = _sum([_number(t.get("input")) for t in tokens])
        output_total = _sum([_number(t.get("output")) for t in tokens])
        cost = _sum([_number(p.get("cost")) for p in finishes])
        return Usage(
            input_tokens=int(input_total) if input_total is not None else None,
            output_tokens=int(output_total) if output_total is not None else None,
            cost_usd=float(cost) if cost is not None else None,
            raw={"schema": "UNVERIFIED", "steps": len(finishes)},
        )

    def probe_spec(self) -> ProbeSpec:
        return ProbeSpec(
            command="opencode",
            help_args=("run", "--help"),
            required_flags={
                "format": ("--format",),
                "dir": ("--dir",),
                "agent": ("--agent",),
            },
        )


def register(registry: RunnerRegistry) -> None:
    registry.register(OpenCodeCliRunner())
