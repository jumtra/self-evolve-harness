from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from seh.contracts import RunContext, RunResult, TerminalState, Verdict, VerdictStatus
from seh.contracts.state import UnitState
from seh.contracts.task import NodeKind, RiskRank, WorkUnit
from seh.runtime.graph import WorkflowGraph
from seh.runtime.repair import run_unit_with_repair
from seh.runtime.runners.fake import FakeCliRunner
from seh.runtime.scheduler import Budget, NodeOutcome, Scheduler


async def test_only_the_failing_unit_is_retried() -> None:
    nodes = tuple(
        WorkUnit(f"u{i}", NodeKind.CODE, (), {}, "schema://s", (), ("c",), RiskRank.R0)
        for i in range(4)
    )
    runners = {
        n.node_id: FakeCliRunner(
            "fake",
            lambda prompt, ctx: RunResult(
                "r", "fake", TerminalState.SUCCESS, 0, "完了しました", None, (), None, None
            ),
        )
        for n in nodes
    }
    checks_of_u3 = 0

    async def checker(unit: WorkUnit, run: RunResult, cwd: Path) -> Verdict:
        nonlocal checks_of_u3
        if unit.node_id == "u3":
            checks_of_u3 += 1
            if checks_of_u3 == 1:
                return Verdict("u3", VerdictStatus.FAIL, "c", "BAD", (), (), 1, 3)
        return Verdict(unit.node_id, VerdictStatus.PASS, "c", "OK", (), (), 1, 3)

    def compose(unit: WorkUnit, feedback: Mapping[str, object] | None) -> str:
        return unit.node_id

    def context_for(unit: WorkUnit, attempt: int) -> RunContext:
        return RunContext(Path("/wt"), Path("/wt"), 60, ())

    async def run_node(unit: WorkUnit, deps: Mapping[str, Mapping[str, object]]) -> NodeOutcome:
        return await run_unit_with_repair(
            unit,
            runner=runners[unit.node_id],
            checker=checker,
            compose=compose,
            context_for=context_for,
        )

    state = await Scheduler(
        WorkflowGraph.build(nodes, ()),
        run_node,
        Budget(max_parallel=4, max_total_seconds=60),
        run_id="run-1",
    ).run()

    assert all(s is UnitState.PASSED for s in state.states.values())
    assert [len(runners[f"u{i}"].calls) for i in range(4)] == [1, 1, 1, 2]
