"""独立した証拠と各ノードの状態から最終結果を決定する。"""

from collections.abc import Mapping, Sequence

from seh.contracts import FinalOutput, NodeKind
from seh.contracts.state import UnitState
from seh.runtime.graph import WorkflowGraph
from seh.runtime.scheduler import SchedulerState


def final_gate(
    state: SchedulerState,
    graph: WorkflowGraph,
    evidence: Mapping[str, Sequence[str]],
    *,
    task_id: str,
) -> FinalOutput:
    reasons = [o.reason for o in state.outcomes.values() if o.reason]
    changed: set[str] = set()
    for outcome in state.outcomes.values():
        files = outcome.outputs.get("changed_files", [])
        if isinstance(files, (list, tuple)):
            changed.update(x for x in files if isinstance(x, str))
    missing = []
    for node in graph.nodes:
        if node.kind not in (NodeKind.WORKER, NodeKind.CODE):
            continue
        if state.states.get(node.node_id) is UnitState.PASSED:
            outcome = state.outcomes.get(node.node_id)
            verdict = outcome.outputs.get("verdict") if outcome else None
            if (
                not evidence.get(node.node_id)
                or not isinstance(verdict, dict)
                or verdict.get("status") != "PASS"
            ):
                missing.append(node.node_id)
    if not any(n.kind is NodeKind.GATE for n in graph.nodes):
        reasons.append("NO_GATE")
    if missing:
        reasons.append("MISSING_EVIDENCE:" + ",".join(missing))
    states = set(state.states.values())
    if missing or "NO_GATE" in reasons or UnitState.FAILED in states:
        status = UnitState.FAILED
    elif UnitState.WAITING_APPROVAL in states:
        status = UnitState.WAITING_APPROVAL
    elif UnitState.CANCELLED in states:
        status = UnitState.CANCELLED
    elif states != {UnitState.PASSED} or state.stopped_reason:
        status = UnitState.BLOCKED
    else:
        status = UnitState.PASSED
    if state.stopped_reason:
        reasons.append(state.stopped_reason)
    refs = tuple(sorted({r for values in evidence.values() for r in values}))
    return FinalOutput(
        task_id,
        status,
        "; ".join(reasons) or status.value,
        tuple(sorted(changed)),
        refs,
        tuple(reasons),
        True,
    )


def final_output_to_dict(out: FinalOutput) -> dict[str, object]:
    return {
        "task_id": out.task_id,
        "status": out.status.value,
        "summary": out.summary,
        "changed_files": list(out.changed_files),
        "evidence_refs": list(out.evidence_refs),
        "remaining_risks": list(out.remaining_risks),
        "requires_human_approval": out.requires_human_approval,
    }
