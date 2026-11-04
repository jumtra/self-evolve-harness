from __future__ import annotations

from pathlib import Path

from seh.contracts import TerminalState
from seh.contracts.state import UnitState
from seh.runtime.checkpoint import CheckpointStore, next_attempt, remaining_budget
from seh.runtime.repair import AttemptRecord
from seh.runtime.scheduler import Budget, NodeOutcome, SchedulerState


def test_load_returns_none_when_nothing_saved(tmp_path: Path) -> None:
    assert CheckpointStore(tmp_path, "run-1").load() is None


def test_state_budget_and_attempts_round_trip(tmp_path: Path) -> None:
    store = CheckpointStore(tmp_path, "run-1")
    state = SchedulerState(
        {"a": UnitState.PASSED, "b": UnitState.RUNNING},
        {"a": NodeOutcome("a", UnitState.PASSED, None, 0.5, {"attempts": 1})},
    )
    record = AttemptRecord(1, "r1", TerminalState.SUCCESS, "FAIL", "BAD", ("e://1",))

    store.save_state(state, budget_spent={"elapsed_seconds": 12.0, "cost_usd": 0.5})
    store.append_attempt("b", record)
    loaded = CheckpointStore(tmp_path, "run-1").load()

    assert loaded is not None
    assert loaded.state.states == state.states
    assert loaded.state.outcomes["a"].cost_usd == 0.5
    assert loaded.budget_spent == {"elapsed_seconds": 12.0, "cost_usd": 0.5}
    assert loaded.attempts["b"] == (record,)


def test_list_runs_returns_saved_run_ids(tmp_path: Path) -> None:
    state = SchedulerState({"a": UnitState.PENDING})
    CheckpointStore(tmp_path, "run-b").save_state(state, budget_spent={})
    CheckpointStore(tmp_path, "run-a").save_state(state, budget_spent={})

    assert CheckpointStore.list_runs(tmp_path) == ["run-a", "run-b"]


def test_list_runs_is_empty_without_state_dir(tmp_path: Path) -> None:
    assert CheckpointStore.list_runs(tmp_path) == []


def test_next_attempt_continues_after_highest_recorded() -> None:
    records = (
        AttemptRecord(1, "r1", TerminalState.SUCCESS, "FAIL", "BAD", ()),
        AttemptRecord(2, "r2", TerminalState.SUCCESS, "FAIL", "BAD", ()),
    )

    assert next_attempt(records) == 3
    assert next_attempt(()) == 1


def test_remaining_budget_subtracts_spent_and_floors_at_zero() -> None:
    total = Budget(max_parallel=3, max_total_seconds=100.0, max_cost_usd=2.0)

    remaining = remaining_budget(total, {"elapsed_seconds": 30.0, "cost_usd": 5.0})

    assert remaining == Budget(max_parallel=3, max_total_seconds=70.0, max_cost_usd=0.0)


def test_remaining_budget_keeps_unlimited_cost_unlimited() -> None:
    total = Budget(max_parallel=1, max_total_seconds=10.0)

    assert remaining_budget(total, {"elapsed_seconds": 4.0}).max_cost_usd is None
