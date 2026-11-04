"""Generate -> Evaluate -> Repair ループ。評定は注入された独立 Checker だけが行う。"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from seh.contracts import (
    CliAgentRunner,
    RunContext,
    RunResult,
    TerminalState,
    Verdict,
    VerdictStatus,
    WorkUnit,
)
from seh.contracts.state import UnitState
from seh.runtime.scheduler import NodeOutcome

UnitChecker = Callable[[WorkUnit, RunResult, Path], Awaitable[Verdict]]
PromptComposer = Callable[[WorkUnit, Mapping[str, object] | None], str]
ContextFactory = Callable[[WorkUnit, int], RunContext]

_TERMINAL_TO_STATE = {
    TerminalState.BLOCKED_AUTH: UnitState.BLOCKED,
    TerminalState.POLICY_BLOCKED: UnitState.BLOCKED,
    TerminalState.UNSUPPORTED: UnitState.BLOCKED,
    TerminalState.CANCELLED: UnitState.CANCELLED,
}


@dataclass(frozen=True)
class AttemptRecord:
    attempt: int
    run_id: str
    terminal_state: TerminalState
    verdict_status: str | None
    reason_code: str | None
    evidence_refs: tuple[str, ...]


def _verdict_dict(verdict: Verdict) -> dict[str, object]:
    return {
        "status": verdict.status.value,
        "check_id": verdict.check_id,
        "reason_code": verdict.reason_code,
        "evidence": [e.uri for e in verdict.evidence],
    }


async def run_unit_with_repair(
    unit: WorkUnit,
    *,
    runner: CliAgentRunner,
    checker: UnitChecker,
    compose: PromptComposer,
    context_for: ContextFactory,
    max_attempts: int = 3,
    start_attempt: int = 1,
    on_attempt: Callable[[AttemptRecord], None] | None = None,
) -> NodeOutcome:
    """start_attempt は再開時に通算 max_attempts を超えないための引き継ぎ番号。"""
    feedback: Mapping[str, object] | None = None
    last_verdict: Verdict | None = None
    cost = 0.0
    attempt = start_attempt
    while attempt <= max_attempts:
        context = context_for(unit, attempt)
        run = await runner.run_once(compose(unit, feedback), context)
        if run.usage is not None and run.usage.cost_usd is not None:
            cost += run.usage.cost_usd
        if run.terminal_state is not TerminalState.SUCCESS:
            _notify(on_attempt, attempt, run, None)
            state = _TERMINAL_TO_STATE.get(run.terminal_state, UnitState.FAILED)
            return NodeOutcome(unit.node_id, state, run.terminal_state.value, cost)
        try:
            verdict = await checker(unit, run, context.cwd)
        except Exception:
            _notify(on_attempt, attempt, run, None)
            return NodeOutcome(unit.node_id, UnitState.FAILED, "CHECKER_ERROR", cost)
        _notify(on_attempt, attempt, run, verdict)
        last_verdict = verdict
        if verdict.status is VerdictStatus.BLOCKED:
            return NodeOutcome(unit.node_id, UnitState.BLOCKED, verdict.reason_code, cost)
        if verdict.passed:
            return NodeOutcome(
                unit.node_id,
                UnitState.PASSED,
                None,
                cost,
                _outputs(verdict, attempt),
            )
        feedback = verdict.as_repair_input()
        attempt += 1
    outputs = _outputs(last_verdict, max_attempts) if last_verdict is not None else {}
    return NodeOutcome(unit.node_id, UnitState.FAILED, "MAX_ATTEMPTS_REACHED", cost, outputs)


def _outputs(verdict: Verdict, attempts: int) -> dict[str, object]:
    return {
        "verdict": _verdict_dict(verdict),
        "attempts": attempts,
        "evidence": [e.uri for e in verdict.evidence],
    }


def _notify(
    on_attempt: Callable[[AttemptRecord], None] | None,
    attempt: int,
    run: RunResult,
    verdict: Verdict | None,
) -> None:
    if on_attempt is None:
        return
    refs = run.evidence_refs + tuple(e.uri for e in verdict.evidence) if verdict else ()
    on_attempt(
        AttemptRecord(
            attempt,
            run.run_id,
            run.terminal_state,
            verdict.status.value if verdict else None,
            verdict.reason_code if verdict else run.error_code,
            refs or run.evidence_refs,
        )
    )
