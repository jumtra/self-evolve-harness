"""CLI Runner 共通基底。ベンダー別実装は 4 つのフックだけ書けばよい。"""

from __future__ import annotations

import abc
import asyncio
import hashlib
import os
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import cast

from seh.artifacts import ArtifactStore
from seh.contracts import (
    RunContext,
    RunResult,
    RuntimeCapabilityReport,
    TerminalState,
    Usage,
)
from seh.redaction import mask_jsonl, mask_obj, mask_text
from seh.runtime.cli_capability import ProbeSpec, probe_cli
from seh.runtime.process import ProcessResult, build_env, run_process


class InvalidEventStream(Exception):
    """stdout がイベント列として解釈できない。"""


@dataclass(frozen=True)
class Invocation:
    argv: tuple[str, ...]
    stdin: bytes | None
    env_extra: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class TerminalDecision:
    state: TerminalState
    error_code: str | None
    final_response: str | None
    structured_output: object | None = None
    permission_denials: tuple[Mapping[str, object], ...] = ()


class BaseCliRunner(abc.ABC):
    host: str
    command: str
    supports_read_only = False

    def __init__(self, *, artifacts: ArtifactStore | None = None) -> None:
        self._artifacts = artifacts
        self._tasks: dict[str, asyncio.Future[ProcessResult]] = {}

    @abc.abstractmethod
    def build_invocation(self, prompt: str, context: RunContext) -> Invocation: ...

    @abc.abstractmethod
    def parse_events(self, stdout: bytes) -> list[Mapping[str, object]]: ...

    @abc.abstractmethod
    def detect_terminal(
        self, events: Sequence[Mapping[str, object]], exit_code: int | None, stderr: bytes
    ) -> TerminalDecision: ...

    @abc.abstractmethod
    def normalize_usage(self, events: Sequence[Mapping[str, object]]) -> Usage | None: ...

    @abc.abstractmethod
    def probe_spec(self) -> ProbeSpec: ...

    def probe(self) -> RuntimeCapabilityReport:
        return probe_cli(self.host, self.probe_spec())

    def active_run_ids(self) -> tuple[str, ...]:
        return tuple(self._tasks)

    async def cancel(self, run_id: str) -> None:
        task = self._tasks.get(run_id)
        if task is not None:
            task.cancel()

    def _result(
        self,
        run_id: str,
        state: TerminalState,
        error_code: str | None,
        proc: ProcessResult | None = None,
        evidence_refs: tuple[str, ...] = (),
    ) -> RunResult:
        return RunResult(
            run_id=run_id,
            host=self.host,
            terminal_state=state,
            exit_code=proc.exit_code if proc else None,
            final_response=None,
            event_log_digest=hashlib.sha256(proc.stdout).hexdigest() if proc else None,
            evidence_refs=evidence_refs,
            usage=None,
            error_code=error_code,
        )

    def _save_evidence(self, run_id: str, proc: ProcessResult) -> tuple[str, ...]:
        if self._artifacts is None:
            return ()
        # 秘密が成果物へ残らないよう保存前に必ずマスクする
        events = self._artifacts.put(
            run_id, "events.jsonl", mask_jsonl(proc.stdout.decode(errors="replace"))
        )
        stderr = self._artifacts.put(
            run_id, "stderr.txt", mask_text(proc.stderr.decode(errors="replace"))
        )
        return (events.uri, stderr.uri)

    async def _execute(self, run_id: str, prompt: str, context: RunContext) -> ProcessResult:
        invocation = self.build_invocation(prompt, context)
        env = build_env(context.env_allowlist, os.environ, invocation.env_extra)
        # 外部 cancel() が呼び出し元タスクを巻き込まないよう、プロセス実行は別タスクにする
        task = asyncio.ensure_future(
            run_process(
                invocation.argv,
                cwd=context.cwd,
                env=env,
                stdin=invocation.stdin,
                timeout_seconds=context.deadline_seconds,
            )
        )
        self._tasks[run_id] = task
        try:
            return await task
        finally:
            del self._tasks[run_id]

    async def run_once(self, prompt: str, context: RunContext) -> RunResult:
        run_id = uuid.uuid4().hex
        if not context.cwd.is_dir() or context.deadline_seconds <= 0:
            return self._result(run_id, TerminalState.FAILED, "INVALID_CONTEXT")
        if context.permissions_profile == "read-only" and not self.supports_read_only:
            return self._result(run_id, TerminalState.UNSUPPORTED, "READ_ONLY_UNSUPPORTED")
        try:
            proc = await self._execute(run_id, prompt, context)
        except FileNotFoundError:
            return self._result(run_id, TerminalState.UNSUPPORTED, "CLI_NOT_FOUND")
        except PermissionError:
            return self._result(run_id, TerminalState.UNSUPPORTED, "CLI_NOT_EXECUTABLE")
        except asyncio.CancelledError:
            current = asyncio.current_task()
            if current is not None and current.cancelling() > 0:
                raise
            return self._result(run_id, TerminalState.CANCELLED, "CANCELLED")

        refs = self._save_evidence(run_id, proc)
        if proc.timed_out:
            return self._result(run_id, TerminalState.TIMED_OUT, "TIMED_OUT", proc, refs)
        if proc.cancelled:
            return self._result(run_id, TerminalState.CANCELLED, "CANCELLED", proc, refs)
        if proc.stdout_truncated:
            return self._result(
                run_id, TerminalState.INVALID_OUTPUT, "OUTPUT_TRUNCATED", proc, refs
            )
        try:
            events = self.parse_events(proc.stdout)
        except InvalidEventStream:
            return self._result(
                run_id, TerminalState.INVALID_OUTPUT, "INVALID_EVENT_STREAM", proc, refs
            )

        decision = self.detect_terminal(events, proc.exit_code, proc.stderr)
        state, error_code = decision.state, decision.error_code
        # exit=0 かつ SUCCESS でも権限拒否が 1 件でもあれば成功扱いにしない（FR-091）
        if state is TerminalState.SUCCESS and decision.permission_denials:
            state, error_code = TerminalState.FAILED, "PERMISSION_DENIED"
        # ベンダーが SUCCESS と言っても非 0 終了を成功にしない
        if state is TerminalState.SUCCESS and proc.exit_code != 0:
            state, error_code = TerminalState.FAILED, "NONZERO_EXIT"
        return RunResult(
            run_id=run_id,
            host=self.host,
            terminal_state=state,
            exit_code=proc.exit_code,
            final_response=(
                mask_text(decision.final_response) if decision.final_response is not None else None
            ),
            event_log_digest=hashlib.sha256(proc.stdout).hexdigest(),
            evidence_refs=refs,
            usage=self.normalize_usage(events),
            error_code=error_code,
            structured_output=mask_obj(decision.structured_output),
            permission_denials=cast(
                "tuple[Mapping[str, object], ...]", mask_obj(decision.permission_denials)
            ),
        )
