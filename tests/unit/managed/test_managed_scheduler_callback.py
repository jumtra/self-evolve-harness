from __future__ import annotations

from collections.abc import Mapping

from seh.contracts.state import UnitState
from seh.contracts.task import Edge, NodeKind, RiskRank, WorkUnit
from seh.runtime.graph import WorkflowGraph
from seh.runtime.scheduler import Budget, NodeOutcome, Scheduler, SchedulerState


async def test_on_transition_is_called_after_each_move_with_outcome_already_recorded() -> None:
    nodes = (
        WorkUnit("a", NodeKind.CODE, (), {}, "schema://a", (), (), RiskRank.R0),
        WorkUnit("b", NodeKind.CODE, ("a",), {"x": ""}, "schema://b", (), (), RiskRank.R0),
    )
    edges = (Edge("a", "out", "b", "x"),)
    snapshots: list[tuple[dict[str, UnitState], set[str]]] = []

    def on_transition(state: SchedulerState) -> None:
        snapshots.append((dict(state.states), set(state.outcomes)))

    async def run_node(unit: WorkUnit, deps: Mapping[str, Mapping[str, object]]) -> NodeOutcome:
        return NodeOutcome(unit.node_id, UnitState.PASSED, None)

    scheduler = Scheduler(
        WorkflowGraph.build(nodes, edges),
        run_node,
        Budget(max_parallel=1, max_total_seconds=60),
        run_id="r1",
        on_transition=on_transition,
    )

    await scheduler.run()

    # a: READY, RUNNING, VERIFYING, PASSED / b: 同じ 4 遷移
    assert len(snapshots) == 8
    states_a_passed, outcomes_at_a_passed = snapshots[3]
    assert states_a_passed["a"] is UnitState.PASSED
    assert "a" in outcomes_at_a_passed
    states_last, outcomes_last = snapshots[-1]
    assert set(states_last.values()) == {UnitState.PASSED}
    assert outcomes_last == {"a", "b"}


async def test_on_transition_sees_blocked_downstream_with_outcome() -> None:
    nodes = (
        WorkUnit("a", NodeKind.CODE, (), {}, "schema://a", (), (), RiskRank.R0),
        WorkUnit("b", NodeKind.CODE, ("a",), {"x": ""}, "schema://b", (), (), RiskRank.R0),
    )
    edges = (Edge("a", "out", "b", "x"),)
    last: list[SchedulerState] = []

    async def run_node(unit: WorkUnit, deps: Mapping[str, Mapping[str, object]]) -> NodeOutcome:
        return NodeOutcome(unit.node_id, UnitState.FAILED, "BAD")

    def on_transition(state: SchedulerState) -> None:
        last.append(SchedulerState(dict(state.states), dict(state.outcomes)))

    scheduler = Scheduler(
        WorkflowGraph.build(nodes, edges),
        run_node,
        Budget(max_parallel=1, max_total_seconds=60),
        run_id="r1",
        on_transition=on_transition,
    )

    await scheduler.run()

    assert last[-1].states["b"] is UnitState.BLOCKED
    assert last[-1].outcomes["b"].reason == "UPSTREAM_FAILED:a"
