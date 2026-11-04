from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field

from seh.contracts.state import UnitState, transition
from seh.contracts.task import WorkUnit
from seh.runtime.graph import WorkflowGraph
from seh.trace import TraceWriter

_S = UnitState
_REPORTABLE = frozenset({_S.PASSED, _S.FAILED, _S.BLOCKED, _S.CANCELLED, _S.WAITING_APPROVAL})
_UPSTREAM_BAD = frozenset({_S.FAILED, _S.BLOCKED, _S.CANCELLED})
# 再開時は途中状態を信用せず、再検証のため最初からやり直す（02 §5.3）
_IN_FLIGHT = frozenset({_S.READY, _S.RUNNING, _S.VERIFYING, _S.REPAIRING})


@dataclass(frozen=True)
class NodeOutcome:
    node_id: str
    state: UnitState
    reason: str | None
    cost_usd: float | None = None
    outputs: Mapping[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return {
            "node_id": self.node_id,
            "state": self.state.value,
            "reason": self.reason,
            "cost_usd": self.cost_usd,
            "outputs": dict(self.outputs),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> NodeOutcome:
        outputs = data.get("outputs")
        cost = data.get("cost_usd")
        reason = data.get("reason")
        return cls(
            node_id=str(data["node_id"]),
            state=UnitState(str(data["state"])),
            reason=None if reason is None else str(reason),
            cost_usd=None if cost is None else float(str(cost)),
            outputs=dict(outputs) if isinstance(outputs, dict) else {},
        )


NodeRunner = Callable[[WorkUnit, Mapping[str, Mapping[str, object]]], Awaitable[NodeOutcome]]


@dataclass(frozen=True)
class Budget:
    max_parallel: int
    max_total_seconds: float
    max_cost_usd: float | None = None


@dataclass
class SchedulerState:
    states: dict[str, UnitState]
    outcomes: dict[str, NodeOutcome] = field(default_factory=dict)
    stopped_reason: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "states": {k: v.value for k, v in self.states.items()},
            "outcomes": {k: v.to_dict() for k, v in self.outcomes.items()},
            "stopped_reason": self.stopped_reason,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> SchedulerState:
        states = data["states"]
        outcomes = data["outcomes"]
        reason = data.get("stopped_reason")
        assert isinstance(states, dict) and isinstance(outcomes, dict)
        return cls(
            states={k: UnitState(v) for k, v in states.items()},
            outcomes={k: NodeOutcome.from_dict(v) for k, v in outcomes.items()},
            stopped_reason=None if reason is None else str(reason),
        )


class Scheduler:
    def __init__(
        self,
        graph: WorkflowGraph,
        run_node: NodeRunner,
        budget: Budget,
        *,
        trace: TraceWriter | None = None,
        run_id: str,
        clock: Callable[[], float] = time.monotonic,
        initial: SchedulerState | None = None,
        on_transition: Callable[[SchedulerState], None] | None = None,
    ) -> None:
        self._on_transition = on_transition
        self._graph = graph
        self._run_node = run_node
        self._budget = budget
        self._trace = trace
        self._run_id = run_id
        self._clock = clock
        self._units = {n.node_id: n for n in graph.nodes}
        self._tasks: dict[str, asyncio.Task[NodeOutcome]] = {}
        self._cancelled = False
        self.max_observed_parallel = 0
        self._state = self._initial_state(initial)

    def _initial_state(self, initial: SchedulerState | None) -> SchedulerState:
        states = dict.fromkeys(self._units, _S.PENDING)
        if initial is None:
            return SchedulerState(states)
        for node_id, state in initial.states.items():
            if node_id in states:
                states[node_id] = _S.PENDING if state in _IN_FLIGHT else state
        outcomes = {k: v for k, v in initial.outcomes.items() if states.get(k) == v.state}
        return SchedulerState(states, outcomes)

    def cancel(self) -> None:
        self._cancelled = True
        for task in self._tasks.values():
            task.cancel()

    async def run(self) -> SchedulerState:
        started_at = self._clock()
        cost = sum(o.cost_usd or 0.0 for o in self._state.outcomes.values())
        while True:
            self._record_stop(started_at, cost)
            if self._state.stopped_reason is None:
                self._block_downstream_of_failures()
                self._start_ready()
            if not self._tasks:
                return self._state
            done, _ = await asyncio.wait(self._tasks.values(), return_when=asyncio.FIRST_COMPLETED)
            for node_id in [n for n, t in self._tasks.items() if t in done]:
                cost += self._finish(node_id, self._tasks.pop(node_id))

    def _record_stop(self, started_at: float, cost: float) -> None:
        if self._state.stopped_reason is not None:
            return
        if self._cancelled:
            self._state.stopped_reason = "CANCELLED"
        elif not self._startable():
            return
        elif self._clock() - started_at > self._budget.max_total_seconds:
            self._state.stopped_reason = "BUDGET_EXCEEDED:time"
        elif self._budget.max_cost_usd is not None and cost > self._budget.max_cost_usd:
            self._state.stopped_reason = "BUDGET_EXCEEDED:cost"

    def _startable(self) -> tuple[str, ...]:
        passed = {n for n, s in self._state.states.items() if s is _S.PASSED}
        touched = {n for n, s in self._state.states.items() if s is not _S.PENDING}
        return self._graph.ready(passed, touched - passed)

    def _block_downstream_of_failures(self) -> None:
        for layer in self._graph.topological_layers():
            for node_id in layer:
                if self._state.states[node_id] is not _S.PENDING:
                    continue
                for dep in self._units[node_id].depends_on:
                    dep_state = self._state.states[dep]
                    if dep_state in _UPSTREAM_BAD:
                        reason = f"UPSTREAM_{dep_state.value}:{dep}"
                        # 永続化コールバックが状態と outcome の不整合を見ないよう先に記録する
                        self._state.outcomes[node_id] = NodeOutcome(node_id, _S.BLOCKED, reason)
                        self._move(node_id, _S.BLOCKED)
                        break

    def _start_ready(self) -> None:
        for node_id in self._startable():
            if len(self._tasks) >= self._budget.max_parallel:
                return
            self._move(node_id, _S.READY)
            self._move(node_id, _S.RUNNING)
            unit = self._units[node_id]
            deps = {d: self._state.outcomes[d].outputs for d in unit.depends_on}
            self._tasks[node_id] = asyncio.create_task(self._guarded(unit, deps))
            self.max_observed_parallel = max(self.max_observed_parallel, len(self._tasks))

    async def _guarded(
        self, unit: WorkUnit, deps: Mapping[str, Mapping[str, object]]
    ) -> NodeOutcome:
        try:
            return await self._run_node(unit, deps)
        except Exception as e:
            return NodeOutcome(unit.node_id, _S.FAILED, f"NODE_ERROR:{type(e).__name__}")

    def _finish(self, node_id: str, task: asyncio.Task[NodeOutcome]) -> float:
        if task.cancelled():
            outcome = NodeOutcome(node_id, _S.CANCELLED, "CANCELLED")
        else:
            outcome = task.result()
        if outcome.state not in _REPORTABLE:
            outcome = NodeOutcome(node_id, _S.FAILED, f"INVALID_OUTCOME:{outcome.state.value}")
        if outcome.state is _S.PASSED:
            self._move(node_id, _S.VERIFYING)
        self._state.outcomes[node_id] = outcome
        self._move(node_id, outcome.state)
        return outcome.cost_usd or 0.0

    def _move(self, node_id: str, nxt: UnitState) -> None:
        current = self._state.states[node_id]
        self._state.states[node_id] = transition(current, nxt)
        if self._trace is not None:
            self._trace.emit(
                "node.transition",
                run_id=self._run_id,
                node_id=node_id,
                data={"from": current.value, "to": nxt.value},
            )
        if self._on_transition is not None:
            self._on_transition(self._state)
