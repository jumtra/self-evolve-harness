"""テスト用 Runner。実ベンダー CLI なしで上位層と基底の写像を検証する。"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence

from seh.artifacts import ArtifactStore
from seh.contracts import RunContext, RunResult, RuntimeCapabilityReport, TerminalState, Usage
from seh.runtime.cli_capability import ProbeSpec
from seh.runtime.runners.base import (
    BaseCliRunner,
    InvalidEventStream,
    Invocation,
    TerminalDecision,
)


class FakeCliRunner:
    def __init__(
        self,
        host: str,
        results: Sequence[RunResult] | Callable[[str, RunContext], RunResult],
    ) -> None:
        self.host = host
        self.calls: list[tuple[str, RunContext]] = []
        self._results = results
        self._index = 0

    def probe(self) -> RuntimeCapabilityReport:
        return RuntimeCapabilityReport(self.host, True, None, None, {}, False, ())

    async def run_once(self, prompt: str, context: RunContext) -> RunResult:
        self.calls.append((prompt, context))
        if callable(self._results):
            return self._results(prompt, context)
        assert self._index < len(self._results), "FakeCliRunner results exhausted"
        result = self._results[self._index]
        self._index += 1
        return result

    async def cancel(self, run_id: str) -> None:
        return None


class ScriptedVendorRunner(BaseCliRunner):
    """`<command> -c <script>` が JSONL を出力する想定の簡易ベンダー。プロンプトは stdin で渡す。"""

    host = "scripted"

    def __init__(
        self,
        script: str,
        *,
        command: str = "python3",
        artifacts: ArtifactStore | None = None,
    ) -> None:
        super().__init__(artifacts=artifacts)
        self.command = command
        self._script = script

    def build_invocation(self, prompt: str, context: RunContext) -> Invocation:
        return Invocation(argv=(self.command, "-c", self._script), stdin=prompt.encode())

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
        result = next((e for e in reversed(events) if e.get("type") == "result"), None)
        if result is None:
            return TerminalDecision(TerminalState.INVALID_OUTPUT, "NO_TERMINAL_EVENT", None)
        text = result.get("text")
        denials = result.get("permission_denials")
        succeeded = result.get("ok") is True
        return TerminalDecision(
            TerminalState.SUCCESS if succeeded else TerminalState.FAILED,
            None if succeeded else "VENDOR_ERROR",
            text if isinstance(text, str) else None,
            permission_denials=tuple(denials) if isinstance(denials, list) else (),
        )

    def normalize_usage(self, events: Sequence[Mapping[str, object]]) -> Usage | None:
        result = next((e for e in reversed(events) if e.get("type") == "result"), None)
        raw = result.get("usage") if result else None
        if not isinstance(raw, dict):
            return None
        return Usage(
            input_tokens=raw.get("input_tokens"),
            output_tokens=raw.get("output_tokens"),
            cost_usd=raw.get("cost_usd"),
            raw=raw,
        )

    def probe_spec(self) -> ProbeSpec:
        return ProbeSpec(command=self.command, required_flags={})
