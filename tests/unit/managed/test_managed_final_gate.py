from __future__ import annotations

from seh.contracts.schema import validate
from seh.contracts.state import UnitState
from seh.contracts.task import Edge, NodeKind, RiskRank, WorkUnit
from seh.runtime.gate import final_gate, final_output_to_dict
from seh.runtime.graph import WorkflowGraph
from seh.runtime.scheduler import NodeOutcome, SchedulerState

WORKER = WorkUnit("w", NodeKind.WORKER, (), {}, "schema://w", ("a.txt",), ("c",), RiskRank.R0)
GATE = WorkUnit("g", NodeKind.GATE, ("w",), {"x": ""}, None, (), (), RiskRank.R0)
GRAPH = WorkflowGraph.build((WORKER, GATE), (Edge("w", "out", "g", "x"),))
PASS_VERDICT = {
    "status": "PASS",
    "check_id": "c",
    "reason_code": "OK",
    "evidence": ["artifact://r/e"],
}


def test_all_passed_with_evidence_is_passed_and_always_needs_human_approval() -> None:
    state = SchedulerState(
        {"w": UnitState.PASSED, "g": UnitState.PASSED},
        {
            "w": NodeOutcome("w", UnitState.PASSED, None, outputs={"verdict": PASS_VERDICT}),
            "g": NodeOutcome(
                "g",
                UnitState.PASSED,
                None,
                outputs={"changed_files": ["a.txt"], "integration_branch": "seh/r/integration"},
            ),
        },
    )

    out = final_gate(state, GRAPH, {"w": ("artifact://r/e",)}, task_id="t1")

    assert out.status is UnitState.PASSED
    assert out.requires_human_approval is True
    assert out.changed_files == ("a.txt",)
    assert out.evidence_refs == ("artifact://r/e",)
    validate("final_output", final_output_to_dict(out))


def test_passed_worker_without_evidence_is_rejected() -> None:
    state = SchedulerState(
        {"w": UnitState.PASSED, "g": UnitState.PASSED},
        {
            "w": NodeOutcome("w", UnitState.PASSED, None, outputs={"verdict": PASS_VERDICT}),
            "g": NodeOutcome("g", UnitState.PASSED, None, outputs={"changed_files": []}),
        },
    )

    out = final_gate(state, GRAPH, {}, task_id="t1")

    assert out.status is UnitState.FAILED
    assert "MISSING_EVIDENCE" in out.summary
    assert out.requires_human_approval is True


def test_passed_worker_without_pass_verdict_is_rejected() -> None:
    state = SchedulerState(
        {"w": UnitState.PASSED, "g": UnitState.PASSED},
        {
            "w": NodeOutcome("w", UnitState.PASSED, None, outputs={}),
            "g": NodeOutcome("g", UnitState.PASSED, None, outputs={"changed_files": []}),
        },
    )

    out = final_gate(state, GRAPH, {"w": ("artifact://r/e",)}, task_id="t1")

    assert out.status is UnitState.FAILED
    assert "MISSING_EVIDENCE" in out.summary


def test_failed_worker_makes_final_failed_even_though_gate_is_blocked() -> None:
    state = SchedulerState(
        {"w": UnitState.FAILED, "g": UnitState.BLOCKED},
        {
            "w": NodeOutcome("w", UnitState.FAILED, "MAX_ATTEMPTS_REACHED"),
            "g": NodeOutcome("g", UnitState.BLOCKED, "UPSTREAM_FAILED:w"),
        },
    )

    out = final_gate(state, GRAPH, {}, task_id="t1")

    assert out.status is UnitState.FAILED
    assert "MAX_ATTEMPTS_REACHED" in out.summary


def test_gate_waiting_approval_is_reported_as_waiting_approval() -> None:
    state = SchedulerState(
        {"w": UnitState.PASSED, "g": UnitState.WAITING_APPROVAL},
        {
            "w": NodeOutcome("w", UnitState.PASSED, None, outputs={"verdict": PASS_VERDICT}),
            "g": NodeOutcome(
                "g",
                UnitState.WAITING_APPROVAL,
                "R2_REQUIRES_APPROVAL",
                outputs={"changed_files": [".claude/settings.json"]},
            ),
        },
    )

    out = final_gate(state, GRAPH, {"w": ("artifact://r/e",)}, task_id="t1")

    assert out.status is UnitState.WAITING_APPROVAL
    assert out.changed_files == (".claude/settings.json",)
    assert out.requires_human_approval is True


def test_pending_nodes_after_budget_stop_are_blocked_and_report_reason() -> None:
    state = SchedulerState(
        {"w": UnitState.PENDING, "g": UnitState.PENDING},
        {},
        stopped_reason="BUDGET_EXCEEDED:time",
    )

    out = final_gate(state, GRAPH, {}, task_id="t1")

    assert out.status is UnitState.BLOCKED
    assert any("BUDGET_EXCEEDED:time" in r for r in out.remaining_risks)


def test_graph_without_gate_node_cannot_pass() -> None:
    graph = WorkflowGraph.build((WORKER,), ())
    state = SchedulerState(
        {"w": UnitState.PASSED},
        {"w": NodeOutcome("w", UnitState.PASSED, None, outputs={"verdict": PASS_VERDICT})},
    )

    out = final_gate(state, graph, {"w": ("artifact://r/e",)}, task_id="t1")

    assert out.status is UnitState.FAILED
    assert "NO_GATE" in out.summary
