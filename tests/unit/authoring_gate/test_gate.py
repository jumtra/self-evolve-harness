from pathlib import Path

from seh.authoring.eval import TriggerResult, TriggerRun
from seh.authoring.gate import GateStatus, evaluate_gate
from seh.contracts import (
    AuthoringRecord,
    AuthoringRisk,
    AuthoringState,
    Diagnostic,
    DiagnosticLevel,
)
from seh.evals.runner import EvalRun, TrialResult


def _record(risk: AuthoringRisk) -> AuthoringRecord:
    return AuthoringRecord(
        id="AUTH-1",
        target_kind="skill",
        target_paths=(".claude/skills/work/SKILL.md",),
        risk=risk,
        exploration={
            "related_existing_modules": [],
            "reuse_decision": "modify_existing",
            "evidence_refs": ["file:.claude/skills/work/SKILL.md"],
        },
        spec={
            "goal": "g",
            "inputs": "i",
            "boundaries": "b",
            "output": "o",
            "feedback": "f",
        },
        state=AuthoringState.COMPARED,
    )


def _root(tmp_path: Path) -> Path:
    skill = tmp_path / ".claude" / "skills" / "work" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("x")
    return tmp_path


def test_behavioral_change_with_all_evidence_passes(tmp_path: Path) -> None:
    root = _root(tmp_path)
    passing = TrialResult("E01", "regression", 0, "PASS", 1, 0, 0, 1.0, 1, 1, 0.0, None, ())
    baseline = EvalRun("b", "t", "V0", {}, {}, (passing,))
    candidate = EvalRun("c", "t", "V0", {}, {}, (passing,))
    trigger = TriggerRun(
        "t1",
        "claude",
        "work",
        (
            TriggerResult("PS-TP-01", "TRIGGER_POS", True, True),
            TriggerResult("PS-TN-01", "TRIGGER_NEG", False, False),
        ),
        "t",
    )

    decision = evaluate_gate(
        _record(AuthoringRisk.BEHAVIORAL),
        root=root,
        risk=AuthoringRisk.BEHAVIORAL,
        lint_errors=[],
        baseline=baseline,
        candidate=candidate,
        triggers={"claude": trigger},
        required_hosts=["claude"],
        approval_ref=None,
        candidate_digests={"skills/work/SKILL.md": "aa"},
        current_digests={"skills/work/SKILL.md": "aa"},
    )

    assert (decision.status, decision.reasons) == (GateStatus.PASS, ())


def test_lint_error_is_fail(tmp_path: Path) -> None:
    root = _root(tmp_path)

    decision = evaluate_gate(
        _record(AuthoringRisk.TEXT_ONLY),
        root=root,
        risk=AuthoringRisk.TEXT_ONLY,
        lint_errors=[Diagnostic(DiagnosticLevel.ERROR, "SKILL_CONTRACT_MISSING:goal", "m")],
        baseline=None,
        candidate=None,
        triggers={},
        required_hosts=[],
        approval_ref=None,
        candidate_digests={},
        current_digests={},
    )

    assert decision.status is GateStatus.FAIL
    assert "LINT_ERROR:SKILL_CONTRACT_MISSING:goal" in decision.reasons


def test_invalid_record_schema_content_is_fail(tmp_path: Path) -> None:
    root = _root(tmp_path)
    record = AuthoringRecord(
        id="AUTH-1",
        target_kind="skill",
        target_paths=(".claude/skills/work/SKILL.md",),
        risk=AuthoringRisk.TEXT_ONLY,
        exploration={"evidence_refs": []},
        spec={"goal": "g"},
    )

    decision = evaluate_gate(
        record,
        root=root,
        risk=AuthoringRisk.TEXT_ONLY,
        lint_errors=[],
        baseline=None,
        candidate=None,
        triggers={},
        required_hosts=[],
        approval_ref=None,
        candidate_digests={},
        current_digests={},
    )

    assert decision.status is GateStatus.FAIL
    assert "EVIDENCE_MISSING" in decision.reasons
    assert "CONTRACT_MISSING:inputs" in decision.reasons


def test_text_only_needs_no_eval_and_passes(tmp_path: Path) -> None:
    root = _root(tmp_path)

    decision = evaluate_gate(
        _record(AuthoringRisk.TEXT_ONLY),
        root=root,
        risk=AuthoringRisk.TEXT_ONLY,
        lint_errors=[],
        baseline=None,
        candidate=None,
        triggers={},
        required_hosts=["claude"],
        approval_ref=None,
        candidate_digests={},
        current_digests={},
    )

    assert decision.status is GateStatus.PASS


def test_high_risk_without_approval_needs_human_even_when_eval_is_missing(
    tmp_path: Path,
) -> None:
    root = _root(tmp_path)

    decision = evaluate_gate(
        _record(AuthoringRisk.HIGH_RISK),
        root=root,
        risk=AuthoringRisk.HIGH_RISK,
        lint_errors=[],
        baseline=None,
        candidate=None,
        triggers={},
        required_hosts=["claude"],
        approval_ref=None,
        candidate_digests={},
        current_digests={},
    )

    assert decision.status is GateStatus.NEEDS_HUMAN
    assert "APPROVAL_REQUIRED" in decision.reasons
    assert "NO_FRESH_EVAL:claude" in decision.reasons


def test_behavioral_without_candidate_or_trigger_run_is_blocked_no_eval(tmp_path: Path) -> None:
    root = _root(tmp_path)

    decision = evaluate_gate(
        _record(AuthoringRisk.BEHAVIORAL),
        root=root,
        risk=AuthoringRisk.BEHAVIORAL,
        lint_errors=[],
        baseline=None,
        candidate=None,
        triggers={},
        required_hosts=["claude", "codex"],
        approval_ref=None,
        candidate_digests={},
        current_digests={},
    )

    assert decision.status is GateStatus.BLOCKED_NO_EVAL
    assert "NO_FRESH_EVAL:outcome" in decision.reasons
    assert "NO_FRESH_EVAL:claude" in decision.reasons
    assert "NO_FRESH_EVAL:codex" in decision.reasons
    assert "NO_BASELINE" in decision.reasons


def test_undetermined_trigger_on_required_agy_blocks_instead_of_passing(tmp_path: Path) -> None:
    root = _root(tmp_path)
    passing = TrialResult("E01", "regression", 0, "PASS", 1, 0, 0, 1.0, 1, 1, 0.0, None, ())
    run = EvalRun("r", "t", "V0", {}, {}, (passing,))
    claude = TriggerRun(
        "t1", "claude", "work", (TriggerResult("PS-TP-01", "TRIGGER_POS", True, True),), "t"
    )
    agy = TriggerRun(
        "t2", "antigravity", "work", (TriggerResult("PS-TP-01", "TRIGGER_POS", True, None),), "t"
    )

    decision = evaluate_gate(
        _record(AuthoringRisk.BEHAVIORAL),
        root=root,
        risk=AuthoringRisk.BEHAVIORAL,
        lint_errors=[],
        baseline=run,
        candidate=run,
        triggers={"claude": claude, "antigravity": agy},
        required_hosts=["claude", "antigravity"],
        approval_ref=None,
        candidate_digests={},
        current_digests={},
    )

    assert decision.status is GateStatus.BLOCKED_NO_EVAL
    assert decision.reasons == ("NO_FRESH_EVAL:antigravity",)


def test_missing_baseline_blocks(tmp_path: Path) -> None:
    root = _root(tmp_path)
    passing = TrialResult("E01", "regression", 0, "PASS", 1, 0, 0, 1.0, 1, 1, 0.0, None, ())
    candidate = EvalRun("c", "t", "V0", {}, {}, (passing,))
    trigger = TriggerRun(
        "t1", "claude", "work", (TriggerResult("PS-TP-01", "TRIGGER_POS", True, True),), "t"
    )

    decision = evaluate_gate(
        _record(AuthoringRisk.BEHAVIORAL),
        root=root,
        risk=AuthoringRisk.BEHAVIORAL,
        lint_errors=[],
        baseline=None,
        candidate=candidate,
        triggers={"claude": trigger},
        required_hosts=["claude"],
        approval_ref=None,
        candidate_digests={},
        current_digests={},
    )

    assert (decision.status, decision.reasons) == (GateStatus.BLOCKED_NO_EVAL, ("NO_BASELINE",))


def test_must_regression_is_fail(tmp_path: Path) -> None:
    root = _root(tmp_path)
    ok = TrialResult("E01", "regression", 0, "PASS", 1, 0, 0, 1.0, 1, 1, 0.0, None, ())
    ng = TrialResult("E01", "regression", 0, "FAIL", 1, 0, 0, 1.0, 1, 1, 0.0, None, ())
    baseline = EvalRun("b", "t", "V0", {}, {}, (ok,))
    candidate = EvalRun("c", "t", "V0", {}, {}, (ng,))
    trigger = TriggerRun(
        "t1", "claude", "work", (TriggerResult("PS-TP-01", "TRIGGER_POS", True, True),), "t"
    )

    decision = evaluate_gate(
        _record(AuthoringRisk.BEHAVIORAL),
        root=root,
        risk=AuthoringRisk.BEHAVIORAL,
        lint_errors=[],
        baseline=baseline,
        candidate=candidate,
        triggers={"claude": trigger},
        required_hosts=["claude"],
        approval_ref=None,
        candidate_digests={},
        current_digests={},
    )

    assert decision.status is GateStatus.FAIL
    assert "MUST_REGRESSION" in decision.reasons


def test_trigger_mismatch_is_fail_for_both_polarities(tmp_path: Path) -> None:
    root = _root(tmp_path)
    ok = TrialResult("E01", "regression", 0, "PASS", 1, 0, 0, 1.0, 1, 1, 0.0, None, ())
    run = EvalRun("r", "t", "V0", {}, {}, (ok,))
    trigger = TriggerRun(
        "t1",
        "claude",
        "work",
        (
            TriggerResult("PS-TP-01", "TRIGGER_POS", True, False),
            TriggerResult("PS-TN-01", "TRIGGER_NEG", False, True),
            TriggerResult("PS-TN-02", "TRIGGER_NEG", False, False),
        ),
        "t",
    )

    decision = evaluate_gate(
        _record(AuthoringRisk.BEHAVIORAL),
        root=root,
        risk=AuthoringRisk.BEHAVIORAL,
        lint_errors=[],
        baseline=run,
        candidate=run,
        triggers={"claude": trigger},
        required_hosts=["claude"],
        approval_ref=None,
        candidate_digests={},
        current_digests={},
    )

    assert decision.status is GateStatus.FAIL
    assert decision.reasons == ("TRIGGER_MISMATCH:PS-TP-01", "TRIGGER_MISMATCH:PS-TN-01")


def test_candidate_changed_after_eval_is_fail(tmp_path: Path) -> None:
    root = _root(tmp_path)
    ok = TrialResult("E01", "regression", 0, "PASS", 1, 0, 0, 1.0, 1, 1, 0.0, None, ())
    run = EvalRun("r", "t", "V0", {}, {}, (ok,))
    trigger = TriggerRun(
        "t1", "claude", "work", (TriggerResult("PS-TP-01", "TRIGGER_POS", True, True),), "t"
    )

    decision = evaluate_gate(
        _record(AuthoringRisk.BEHAVIORAL),
        root=root,
        risk=AuthoringRisk.BEHAVIORAL,
        lint_errors=[],
        baseline=run,
        candidate=run,
        triggers={"claude": trigger},
        required_hosts=["claude"],
        approval_ref=None,
        candidate_digests={"skills/work/SKILL.md": "aa"},
        current_digests={"skills/work/SKILL.md": "bb"},
    )

    assert (decision.status, decision.reasons) == (
        GateStatus.FAIL,
        ("CANDIDATE_CHANGED_AFTER_EVAL",),
    )


def test_high_risk_with_approval_and_full_evidence_passes(tmp_path: Path) -> None:
    root = _root(tmp_path)
    ok = TrialResult("E01", "regression", 0, "PASS", 1, 0, 0, 1.0, 1, 1, 0.0, None, ())
    run = EvalRun("r", "t", "V0", {}, {}, (ok,))
    trigger = TriggerRun(
        "t1", "claude", "work", (TriggerResult("PS-TP-01", "TRIGGER_POS", True, True),), "t"
    )

    decision = evaluate_gate(
        _record(AuthoringRisk.HIGH_RISK),
        root=root,
        risk=AuthoringRisk.HIGH_RISK,
        lint_errors=[],
        baseline=run,
        candidate=run,
        triggers={"claude": trigger},
        required_hosts=["claude"],
        approval_ref="human-tty:2026-11-04T00:00:00Z",
        candidate_digests={},
        current_digests={},
    )

    assert decision.status is GateStatus.PASS
