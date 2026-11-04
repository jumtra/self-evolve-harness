from __future__ import annotations

import asyncio
from collections.abc import Mapping
from pathlib import Path

from seh.contracts.state import UnitState
from seh.contracts.task import Edge, NodeKind, RiskRank, WorkUnit
from seh.runtime.graph import WorkflowGraph
from seh.runtime.scheduler import Budget, NodeOutcome, Scheduler, SchedulerState
from seh.trace import TraceWriter, read_trace


async def test_gate_starts_after_workers_and_parallelism_is_capped() -> None:
    nodes = (
        WorkUnit("s", NodeKind.CODE, (), {}, "schema://s", (), (), RiskRank.R0),
        WorkUnit("w1", NodeKind.CODE, ("s",), {"t": ""}, "schema://w", (), (), RiskRank.R0),
        WorkUnit("w2", NodeKind.CODE, ("s",), {"t": ""}, "schema://w", (), (), RiskRank.R0),
        WorkUnit("w3", NodeKind.CODE, ("s",), {"t": ""}, "schema://w", (), (), RiskRank.R0),
        WorkUnit(
            "g",
            NodeKind.GATE,
            ("w1", "w2", "w3"),
            {"a": "", "b": "", "c": ""},
            None,
            (),
            (),
            RiskRank.R0,
        ),
    )
    edges = (
        Edge("s", "out", "w1", "t"),
        Edge("s", "out", "w2", "t"),
        Edge("s", "out", "w3", "t"),
        Edge("w1", "out", "g", "a"),
        Edge("w2", "out", "g", "b"),
        Edge("w3", "out", "g", "c"),
    )
    events: list[str] = []

    async def run_node(unit: WorkUnit, deps: Mapping[str, Mapping[str, object]]) -> NodeOutcome:
        events.append(f"start:{unit.node_id}")
        await asyncio.sleep(0.01)
        events.append(f"end:{unit.node_id}")
        return NodeOutcome(unit.node_id, UnitState.PASSED, None)

    scheduler = Scheduler(
        WorkflowGraph.build(nodes, edges),
        run_node,
        Budget(max_parallel=2, max_total_seconds=60),
        run_id="r1",
    )

    state = await scheduler.run()

    gate_start = events.index("start:g")
    assert all(events.index(f"end:{w}") < gate_start for w in ("w1", "w2", "w3"))
    assert scheduler.max_observed_parallel == 2
    assert set(state.states.values()) == {UnitState.PASSED}
    assert state.stopped_reason is None


async def test_failure_blocks_only_downstream() -> None:
    nodes = (
        WorkUnit("a", NodeKind.CODE, (), {}, "schema://a", (), (), RiskRank.R0),
        WorkUnit("b", NodeKind.CODE, ("a",), {"x": ""}, "schema://b", (), (), RiskRank.R0),
        WorkUnit("c", NodeKind.CODE, (), {}, "schema://c", (), (), RiskRank.R0),
    )
    edges = (Edge("a", "out", "b", "x"),)
    called: list[str] = []

    async def run_node(unit: WorkUnit, deps: Mapping[str, Mapping[str, object]]) -> NodeOutcome:
        called.append(unit.node_id)
        if unit.node_id == "a":
            return NodeOutcome("a", UnitState.FAILED, "CHECK_FAILED")
        return NodeOutcome(unit.node_id, UnitState.PASSED, None)

    scheduler = Scheduler(
        WorkflowGraph.build(nodes, edges),
        run_node,
        Budget(max_parallel=3, max_total_seconds=60),
        run_id="r1",
    )

    state = await scheduler.run()

    assert state.states == {
        "a": UnitState.FAILED,
        "b": UnitState.BLOCKED,
        "c": UnitState.PASSED,
    }
    assert state.outcomes["b"].reason == "UPSTREAM_FAILED:a"
    assert "b" not in called


async def test_dependency_outputs_are_passed_downstream() -> None:
    nodes = (
        WorkUnit("a", NodeKind.CODE, (), {}, "schema://a", (), (), RiskRank.R0),
        WorkUnit("b", NodeKind.CODE, ("a",), {"x": ""}, "schema://b", (), (), RiskRank.R0),
    )
    edges = (Edge("a", "out", "b", "x"),)
    received: list[Mapping[str, Mapping[str, object]]] = []

    async def run_node(unit: WorkUnit, deps: Mapping[str, Mapping[str, object]]) -> NodeOutcome:
        received.append(deps)
        return NodeOutcome(unit.node_id, UnitState.PASSED, None, outputs={"v": 1})

    scheduler = Scheduler(
        WorkflowGraph.build(nodes, edges),
        run_node,
        Budget(max_parallel=1, max_total_seconds=60),
        run_id="r1",
    )

    await scheduler.run()

    assert received == [{}, {"a": {"v": 1}}]


async def test_resume_skips_passed_and_reruns_running() -> None:
    nodes = (
        WorkUnit("a", NodeKind.CODE, (), {}, "schema://a", (), (), RiskRank.R0),
        WorkUnit("b", NodeKind.CODE, ("a",), {"x": ""}, "schema://b", (), (), RiskRank.R0),
    )
    edges = (Edge("a", "out", "b", "x"),)
    initial = SchedulerState(
        states={"a": UnitState.PASSED, "b": UnitState.RUNNING},
        outcomes={"a": NodeOutcome("a", UnitState.PASSED, None, outputs={"v": 7})},
        stopped_reason="CANCELLED",
    )
    calls: list[str] = []
    received: list[Mapping[str, Mapping[str, object]]] = []

    async def run_node(unit: WorkUnit, deps: Mapping[str, Mapping[str, object]]) -> NodeOutcome:
        calls.append(unit.node_id)
        received.append(deps)
        return NodeOutcome(unit.node_id, UnitState.PASSED, None)

    scheduler = Scheduler(
        WorkflowGraph.build(nodes, edges),
        run_node,
        Budget(max_parallel=2, max_total_seconds=60),
        run_id="r1",
        initial=initial,
    )

    state = await scheduler.run()

    assert calls == ["b"]
    assert received == [{"a": {"v": 7}}]
    assert state.states == {"a": UnitState.PASSED, "b": UnitState.PASSED}
    assert state.stopped_reason is None


async def test_time_budget_stops_new_starts() -> None:
    nodes = (
        WorkUnit("a", NodeKind.CODE, (), {}, "schema://a", (), (), RiskRank.R0),
        WorkUnit("b", NodeKind.CODE, ("a",), {"x": ""}, "schema://b", (), (), RiskRank.R0),
    )
    edges = (Edge("a", "out", "b", "x"),)
    now = [0.0]
    called: list[str] = []

    async def run_node(unit: WorkUnit, deps: Mapping[str, Mapping[str, object]]) -> NodeOutcome:
        called.append(unit.node_id)
        now[0] = 100.0
        return NodeOutcome(unit.node_id, UnitState.PASSED, None)

    scheduler = Scheduler(
        WorkflowGraph.build(nodes, edges),
        run_node,
        Budget(max_parallel=1, max_total_seconds=10),
        run_id="r1",
        clock=lambda: now[0],
    )

    state = await scheduler.run()

    assert called == ["a"]
    assert state.states == {"a": UnitState.PASSED, "b": UnitState.PENDING}
    assert state.stopped_reason == "BUDGET_EXCEEDED:time"


async def test_cost_budget_stops_new_starts() -> None:
    nodes = (
        WorkUnit("a", NodeKind.CODE, (), {}, "schema://a", (), (), RiskRank.R0),
        WorkUnit("b", NodeKind.CODE, ("a",), {"x": ""}, "schema://b", (), (), RiskRank.R0),
    )
    edges = (Edge("a", "out", "b", "x"),)
    called: list[str] = []

    async def run_node(unit: WorkUnit, deps: Mapping[str, Mapping[str, object]]) -> NodeOutcome:
        called.append(unit.node_id)
        return NodeOutcome(unit.node_id, UnitState.PASSED, None, cost_usd=5.0)

    scheduler = Scheduler(
        WorkflowGraph.build(nodes, edges),
        run_node,
        Budget(max_parallel=1, max_total_seconds=60, max_cost_usd=1.0),
        run_id="r1",
    )

    state = await scheduler.run()

    assert called == ["a"]
    assert state.states["b"] == UnitState.PENDING
    assert state.stopped_reason == "BUDGET_EXCEEDED:cost"


async def test_cancel_marks_running_cancelled_and_leaves_unstarted_pending() -> None:
    nodes = (
        WorkUnit("a", NodeKind.CODE, (), {}, "schema://a", (), (), RiskRank.R0),
        WorkUnit("b", NodeKind.CODE, ("a",), {"x": ""}, "schema://b", (), (), RiskRank.R0),
    )
    edges = (Edge("a", "out", "b", "x"),)
    started = asyncio.Event()

    async def run_node(unit: WorkUnit, deps: Mapping[str, Mapping[str, object]]) -> NodeOutcome:
        started.set()
        await asyncio.Event().wait()
        return NodeOutcome(unit.node_id, UnitState.PASSED, None)

    scheduler = Scheduler(
        WorkflowGraph.build(nodes, edges),
        run_node,
        Budget(max_parallel=1, max_total_seconds=60),
        run_id="r1",
    )
    running = asyncio.create_task(scheduler.run())
    await started.wait()

    scheduler.cancel()
    state = await running

    assert state.states == {"a": UnitState.CANCELLED, "b": UnitState.PENDING}
    assert state.stopped_reason == "CANCELLED"


async def test_node_exception_fails_node_and_others_continue() -> None:
    nodes = (
        WorkUnit("a", NodeKind.CODE, (), {}, "schema://a", (), (), RiskRank.R0),
        WorkUnit("c", NodeKind.CODE, (), {}, "schema://c", (), (), RiskRank.R0),
    )

    async def run_node(unit: WorkUnit, deps: Mapping[str, Mapping[str, object]]) -> NodeOutcome:
        if unit.node_id == "a":
            raise RuntimeError("boom")
        return NodeOutcome(unit.node_id, UnitState.PASSED, None)

    scheduler = Scheduler(
        WorkflowGraph.build(nodes, ()),
        run_node,
        Budget(max_parallel=2, max_total_seconds=60),
        run_id="r1",
    )

    state = await scheduler.run()

    assert state.states == {"a": UnitState.FAILED, "c": UnitState.PASSED}
    assert state.outcomes["a"].reason == "NODE_ERROR:RuntimeError"


async def test_waiting_approval_keeps_state_and_does_not_start_downstream() -> None:
    nodes = (
        WorkUnit("a", NodeKind.CODE, (), {}, "schema://a", (), (), RiskRank.R2),
        WorkUnit("b", NodeKind.CODE, ("a",), {"x": ""}, "schema://b", (), (), RiskRank.R0),
    )
    edges = (Edge("a", "out", "b", "x"),)
    called: list[str] = []

    async def run_node(unit: WorkUnit, deps: Mapping[str, Mapping[str, object]]) -> NodeOutcome:
        called.append(unit.node_id)
        return NodeOutcome(unit.node_id, UnitState.WAITING_APPROVAL, "NEEDS_APPROVAL")

    scheduler = Scheduler(
        WorkflowGraph.build(nodes, edges),
        run_node,
        Budget(max_parallel=1, max_total_seconds=60),
        run_id="r1",
    )

    state = await scheduler.run()

    assert called == ["a"]
    assert state.states == {"a": UnitState.WAITING_APPROVAL, "b": UnitState.PENDING}


async def test_transitions_are_traced(tmp_path: Path) -> None:
    nodes = (WorkUnit("a", NodeKind.CODE, (), {}, "schema://a", (), (), RiskRank.R0),)
    trace_path = tmp_path / "trace.jsonl"

    async def run_node(unit: WorkUnit, deps: Mapping[str, Mapping[str, object]]) -> NodeOutcome:
        return NodeOutcome(unit.node_id, UnitState.PASSED, None)

    scheduler = Scheduler(
        WorkflowGraph.build(nodes, ()),
        run_node,
        Budget(max_parallel=1, max_total_seconds=60),
        trace=TraceWriter(trace_path),
        run_id="r1",
    )

    await scheduler.run()

    steps = [(e["data"]["from"], e["data"]["to"]) for e in read_trace(trace_path)]
    assert steps == [
        ("PENDING", "READY"),
        ("READY", "RUNNING"),
        ("RUNNING", "VERIFYING"),
        ("VERIFYING", "PASSED"),
    ]


def test_scheduler_state_round_trips_through_dict() -> None:
    state = SchedulerState(
        states={"a": UnitState.PASSED, "b": UnitState.PENDING},
        outcomes={"a": NodeOutcome("a", UnitState.PASSED, None, cost_usd=0.5, outputs={"k": [1]})},
        stopped_reason="BUDGET_EXCEEDED:cost",
    )

    restored = SchedulerState.from_dict(state.to_dict())

    assert restored == state
