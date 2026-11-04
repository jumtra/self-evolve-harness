from __future__ import annotations

import subprocess
import sys
import textwrap
from collections.abc import Mapping
from pathlib import Path

from seh.contracts import RunContext, RunResult, TerminalState, Verdict, VerdictStatus
from seh.contracts.state import UnitState
from seh.contracts.task import Edge, NodeKind, RiskRank, WorkUnit
from seh.runtime.checkpoint import CheckpointStore, next_attempt
from seh.runtime.graph import WorkflowGraph
from seh.runtime.repair import run_unit_with_repair
from seh.runtime.runners.fake import FakeCliRunner
from seh.runtime.scheduler import Budget, NodeOutcome, Scheduler

CHILD = textwrap.dedent(
    """
    import asyncio, os, sys
    from pathlib import Path
    from seh.contracts import TerminalState
    from seh.contracts.state import UnitState
    from seh.contracts.task import Edge, NodeKind, RiskRank, WorkUnit
    from seh.runtime.checkpoint import CheckpointStore
    from seh.runtime.graph import WorkflowGraph
    from seh.runtime.repair import AttemptRecord
    from seh.runtime.scheduler import Budget, NodeOutcome, Scheduler, SchedulerState

    store = CheckpointStore(Path(sys.argv[1]), "run-1")
    a = WorkUnit("a", NodeKind.CODE, (), {}, "schema://s", (), (), RiskRank.R0)
    b = WorkUnit("b", NodeKind.CODE, ("a",), {"x": ""}, "schema://s", (), (), RiskRank.R0)
    graph = WorkflowGraph.build((a, b), (Edge("a", "o", "b", "x"),))
    a_outcome = NodeOutcome("a", UnitState.PASSED, None)

    async def run_node(unit, deps):
        if unit.node_id == "a":
            return a_outcome
        store.append_attempt(
            "b", AttemptRecord(1, "r1", TerminalState.SUCCESS, "FAIL", "BAD", ())
        )
        store.save_state(
            SchedulerState(
                {"a": UnitState.PASSED, "b": UnitState.RUNNING}, {"a": a_outcome}
            ),
            budget_spent={"elapsed_seconds": 1.0},
        )
        os._exit(1)

    asyncio.run(
        Scheduler(graph, run_node, Budget(1, 60), run_id="run-1").run()
    )
    """
)


async def test_resume_skips_passed_node_and_continues_attempt_numbering(tmp_path: Path) -> None:
    proc = subprocess.run([sys.executable, "-c", CHILD, str(tmp_path)], check=False)
    assert proc.returncode == 1
    a = WorkUnit("a", NodeKind.CODE, (), {}, "schema://s", (), (), RiskRank.R0)
    b = WorkUnit("b", NodeKind.CODE, ("a",), {"x": ""}, "schema://s", (), (), RiskRank.R0)
    graph = WorkflowGraph.build((a, b), (Edge("a", "o", "b", "x"),))
    checkpoint = CheckpointStore(tmp_path, "run-1").load()
    assert checkpoint is not None
    runner = FakeCliRunner(
        "fake",
        lambda prompt, ctx: RunResult(
            "r", "fake", TerminalState.SUCCESS, 0, None, None, (), None, None
        ),
    )
    executed: list[str] = []

    async def checker(unit: WorkUnit, run: RunResult, cwd: Path) -> Verdict:
        return Verdict(unit.node_id, VerdictStatus.FAIL, "c", "BAD", (), (), 1, 3)

    def context_for(unit: WorkUnit, attempt: int) -> RunContext:
        return RunContext(tmp_path, tmp_path, 60, ())

    async def run_node(unit: WorkUnit, deps: Mapping[str, Mapping[str, object]]) -> NodeOutcome:
        executed.append(unit.node_id)
        return await run_unit_with_repair(
            unit,
            runner=runner,
            checker=checker,
            compose=lambda u, f: u.node_id,
            context_for=context_for,
            start_attempt=next_attempt(checkpoint.attempts.get(unit.node_id, ())),
        )

    state = await Scheduler(
        graph, run_node, Budget(1, 60), run_id="run-1", initial=checkpoint.state
    ).run()

    assert executed == ["b"]
    assert state.states["a"] is UnitState.PASSED
    assert state.states["b"] is UnitState.FAILED
    assert len(runner.calls) == 2
