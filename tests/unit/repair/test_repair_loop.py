from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

import pytest

from seh.contracts import RunContext, RunResult, TerminalState, Verdict, VerdictStatus
from seh.contracts.common import Evidence
from seh.contracts.state import UnitState
from seh.contracts.task import NodeKind, RiskRank, WorkUnit
from seh.runtime.repair import AttemptRecord, run_unit_with_repair
from seh.runtime.runners.fake import FakeCliRunner

UNIT = WorkUnit("u1", NodeKind.WORKER, (), {}, None, ("src/**",), ("c1",), RiskRank.R0)


def _compose(unit: WorkUnit, feedback: Mapping[str, object] | None) -> str:
    return f"do {unit.node_id} feedback={feedback}"


def _context_for(unit: WorkUnit, attempt: int) -> RunContext:
    return RunContext(Path("/wt"), Path(f"/wt/{attempt}"), 60, ())


def test_placeholder_imports() -> None:
    assert AttemptRecord is not None


async def test_failed_check_is_fed_back_and_second_attempt_passes() -> None:
    runner = FakeCliRunner(
        "fake",
        lambda prompt, ctx: RunResult(
            "r", "fake", TerminalState.SUCCESS, 0, "完了しました", None, (), None, None
        ),
    )
    feedbacks: list[Mapping[str, object] | None] = []
    verdicts = [
        Verdict(
            "u1", VerdictStatus.FAIL, "lint", "LINT_ERR", (Evidence("e://1", "x"),), ("src",), 1, 3
        ),
        Verdict("u1", VerdictStatus.PASS, "lint", "OK", (), (), 2, 3),
    ]

    async def checker(unit: WorkUnit, run: RunResult, cwd: Path) -> Verdict:
        return verdicts.pop(0)

    def compose(unit: WorkUnit, feedback: Mapping[str, object] | None) -> str:
        feedbacks.append(feedback)
        return _compose(unit, feedback)

    outcome = await run_unit_with_repair(
        UNIT, runner=runner, checker=checker, compose=compose, context_for=_context_for
    )

    assert outcome.state is UnitState.PASSED
    assert outcome.outputs["attempts"] == 2
    assert feedbacks[0] is None
    assert feedbacks[1] is not None and feedbacks[1]["failed_check"] == "lint"
    assert "lint" in runner.calls[1][0]


async def test_always_failing_checker_stops_at_three_attempts() -> None:
    runner = FakeCliRunner(
        "fake",
        lambda prompt, ctx: RunResult(
            "r", "fake", TerminalState.SUCCESS, 0, "完了しました", None, (), None, None
        ),
    )

    async def checker(unit: WorkUnit, run: RunResult, cwd: Path) -> Verdict:
        return Verdict("u1", VerdictStatus.FAIL, "t", "BAD", (), (), 1, 3)

    outcome = await run_unit_with_repair(
        UNIT, runner=runner, checker=checker, compose=_compose, context_for=_context_for
    )

    assert outcome.state is UnitState.FAILED
    assert outcome.reason == "MAX_ATTEMPTS_REACHED"
    assert len(runner.calls) == 3


async def test_each_attempt_gets_its_own_context() -> None:
    runner = FakeCliRunner(
        "fake",
        lambda prompt, ctx: RunResult(
            "r", "fake", TerminalState.SUCCESS, 0, None, None, (), None, None
        ),
    )

    async def checker(unit: WorkUnit, run: RunResult, cwd: Path) -> Verdict:
        return Verdict("u1", VerdictStatus.FAIL, "t", "BAD", (), (), 1, 3)

    await run_unit_with_repair(
        UNIT, runner=runner, checker=checker, compose=_compose, context_for=_context_for
    )

    cwds = [ctx.cwd for _, ctx in runner.calls]
    assert cwds == [Path("/wt/1"), Path("/wt/2"), Path("/wt/3")]


@pytest.mark.parametrize(
    ("terminal", "expected"),
    [
        (TerminalState.BLOCKED_AUTH, UnitState.BLOCKED),
        (TerminalState.POLICY_BLOCKED, UnitState.BLOCKED),
        (TerminalState.UNSUPPORTED, UnitState.BLOCKED),
        (TerminalState.TIMED_OUT, UnitState.FAILED),
        (TerminalState.INVALID_OUTPUT, UnitState.FAILED),
        (TerminalState.FAILED, UnitState.FAILED),
        (TerminalState.CANCELLED, UnitState.CANCELLED),
    ],
)
async def test_non_success_terminal_state_ends_without_repair(
    terminal: TerminalState, expected: UnitState
) -> None:
    runner = FakeCliRunner(
        "fake",
        lambda prompt, ctx: RunResult("r", "fake", terminal, 1, None, None, (), None, "ERR"),
    )
    checked: list[str] = []

    async def checker(unit: WorkUnit, run: RunResult, cwd: Path) -> Verdict:
        checked.append("called")
        return Verdict("u1", VerdictStatus.PASS, "t", "OK", (), (), 1, 3)

    outcome = await run_unit_with_repair(
        UNIT, runner=runner, checker=checker, compose=_compose, context_for=_context_for
    )

    assert outcome.state is expected
    assert len(runner.calls) == 1
    assert checked == []


async def test_checker_exception_fails_with_checker_error() -> None:
    runner = FakeCliRunner(
        "fake",
        lambda prompt, ctx: RunResult(
            "r", "fake", TerminalState.SUCCESS, 0, "完了しました", None, (), None, None
        ),
    )

    async def checker(unit: WorkUnit, run: RunResult, cwd: Path) -> Verdict:
        raise RuntimeError("boom")

    outcome = await run_unit_with_repair(
        UNIT, runner=runner, checker=checker, compose=_compose, context_for=_context_for
    )

    assert outcome.state is UnitState.FAILED
    assert outcome.reason == "CHECKER_ERROR"
    assert len(runner.calls) == 1


async def test_blocked_verdict_ends_as_blocked() -> None:
    runner = FakeCliRunner(
        "fake",
        lambda prompt, ctx: RunResult(
            "r", "fake", TerminalState.SUCCESS, 0, None, None, (), None, None
        ),
    )

    async def checker(unit: WorkUnit, run: RunResult, cwd: Path) -> Verdict:
        return Verdict("u1", VerdictStatus.BLOCKED, "t", "NO_TOOL", (), (), 1, 3)

    outcome = await run_unit_with_repair(
        UNIT, runner=runner, checker=checker, compose=_compose, context_for=_context_for
    )

    assert outcome.state is UnitState.BLOCKED
    assert len(runner.calls) == 1


async def test_on_attempt_reports_each_attempt_and_start_attempt_limits_remaining() -> None:
    runner = FakeCliRunner(
        "fake",
        lambda prompt, ctx: RunResult(
            "run-x", "fake", TerminalState.SUCCESS, 0, None, None, (), None, None
        ),
    )
    records: list[AttemptRecord] = []

    async def checker(unit: WorkUnit, run: RunResult, cwd: Path) -> Verdict:
        return Verdict("u1", VerdictStatus.FAIL, "t", "BAD", (), (), 1, 3)

    outcome = await run_unit_with_repair(
        UNIT,
        runner=runner,
        checker=checker,
        compose=_compose,
        context_for=_context_for,
        start_attempt=2,
        on_attempt=records.append,
    )

    assert [r.attempt for r in records] == [2, 3]
    assert records[0].verdict_status == "FAIL"
    assert records[0].reason_code == "BAD"
    assert len(runner.calls) == 2
    assert outcome.reason == "MAX_ATTEMPTS_REACHED"
