from pathlib import Path

import pytest

from seh.contracts import RunContext, RunResult, TerminalState
from seh.runtime.agent_runner import RunnerRegistry
from seh.runtime.runners.fake import FakeCliRunner


async def test_fake_runner_returns_results_in_order_and_records_calls():
    first = RunResult(
        run_id="r",
        host="fake",
        terminal_state=TerminalState.SUCCESS,
        exit_code=0,
        final_response="ok",
        event_log_digest=None,
        evidence_refs=(),
        usage=None,
        error_code=None,
    )
    second = RunResult(
        run_id="r",
        host="fake",
        terminal_state=TerminalState.SUCCESS,
        exit_code=0,
        final_response="ok",
        event_log_digest=None,
        evidence_refs=(),
        usage=None,
        error_code=None,
    )
    runner = FakeCliRunner("fake", [first, second])
    context = RunContext(Path("/w"), Path("/w"), 5, ("PATH",))

    got_first = await runner.run_once("p1", context)
    got_second = await runner.run_once("p2", context)

    assert (got_first, got_second) == (first, second)
    assert runner.calls == [("p1", context), ("p2", context)]


async def test_fake_runner_asserts_when_results_exhausted():
    runner = FakeCliRunner("fake", [])
    context = RunContext(Path("/w"), Path("/w"), 5, ("PATH",))

    with pytest.raises(AssertionError):
        await runner.run_once("p", context)


async def test_fake_runner_accepts_callable_results():
    runner = FakeCliRunner(
        "fake",
        lambda prompt, _ctx: RunResult(
            run_id="r",
            host=prompt,
            terminal_state=TerminalState.SUCCESS,
            exit_code=0,
            final_response="ok",
            event_log_digest=None,
            evidence_refs=(),
            usage=None,
            error_code=None,
        ),
    )
    context = RunContext(Path("/w"), Path("/w"), 5, ("PATH",))

    got = await runner.run_once("hostx", context)

    assert got.host == "hostx"


def test_registry_returns_registered_runner_by_host():
    registry = RunnerRegistry()
    runner = FakeCliRunner("fake", [])
    registry.register(runner)

    assert registry.get("fake") is runner


def test_registry_raises_key_error_for_unknown_host():
    registry = RunnerRegistry()

    with pytest.raises(KeyError):
        registry.get("nope")
