import json
from pathlib import Path

import pytest

from seh.authoring.classify import FileChange, classify_change
from seh.authoring.eval import TriggerResult, TriggerRun
from seh.authoring.gate import GateStatus, evaluate_gate
from seh.cli import main
from seh.contracts import AuthoringRecord, AuthoringRisk, AuthoringState
from seh.evals.report import to_json
from seh.evals.runner import EvalRun, TrialResult

PASS_TRIAL = TrialResult("E01", "regression", 0, "PASS", 1, 0, 0, 1.0, 1, 1, 0.0, None, ())
FAIL_TRIAL = TrialResult("E01", "regression", 0, "FAIL", 1, 0, 0, 1.0, 1, 1, 0.0, None, ())


def test_description_change_requires_both_trigger_and_outcome_evaluation_a03(
    tmp_path: Path,
) -> None:
    scenario = json.loads(
        Path("tests/fixtures/prompt_skill/authoring/A03.json").read_text(encoding="utf-8")
    )
    changed = scenario["input"]["changed_files"][0]
    before = "---\nname: work\ndescription: 開発依頼で使う。バグ修正と実装を扱う\n---\n本文\n"
    after = "---\nname: work\ndescription: 開発依頼で使う\n---\n本文\n"
    classification = classify_change(FileChange(changed, before, after))
    assert classification is not None
    risk = classification.risk
    skill = tmp_path / changed
    skill.parent.mkdir(parents=True)
    skill.write_text(after)
    record = AuthoringRecord(
        id="AUTH-3",
        target_kind="skill",
        target_paths=(changed,),
        risk=risk,
        exploration={"evidence_refs": [f"file:{changed}"]},
        spec={"goal": "g", "inputs": "i", "boundaries": "b", "output": "o", "feedback": "f"},
        state=AuthoringState.COMPARED,
    )
    outcome = EvalRun("r", "t", "V0", {}, {}, (PASS_TRIAL,))
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

    trigger_only = evaluate_gate(
        record,
        root=tmp_path,
        risk=risk,
        lint_errors=[],
        baseline=outcome,
        candidate=None,
        triggers={"claude": trigger},
        required_hosts=["claude"],
        approval_ref=None,
        candidate_digests={},
        current_digests={},
    )
    outcome_only = evaluate_gate(
        record,
        root=tmp_path,
        risk=risk,
        lint_errors=[],
        baseline=outcome,
        candidate=outcome,
        triggers={},
        required_hosts=["claude"],
        approval_ref=None,
        candidate_digests={},
        current_digests={},
    )
    both = evaluate_gate(
        record,
        root=tmp_path,
        risk=risk,
        lint_errors=[],
        baseline=outcome,
        candidate=outcome,
        triggers={"claude": trigger},
        required_hosts=["claude"],
        approval_ref=None,
        candidate_digests={},
        current_digests={},
    )

    assert scenario["expected"]["state"] == "AWAITING_EVAL"
    assert risk is AuthoringRisk.BEHAVIORAL
    assert (trigger_only.status, trigger_only.reasons) == (
        GateStatus.BLOCKED_NO_EVAL,
        ("NO_FRESH_EVAL:outcome",),
    )
    assert (outcome_only.status, outcome_only.reasons) == (
        GateStatus.BLOCKED_NO_EVAL,
        ("NO_FRESH_EVAL:claude",),
    )
    assert both.status is GateStatus.PASS


def test_allowed_tools_addition_is_high_risk_and_needs_human_a05(tmp_path: Path) -> None:
    scenario = json.loads(
        Path("tests/fixtures/prompt_skill/authoring/A05.json").read_text(encoding="utf-8")
    )
    changed = scenario["input"]["changed_files"][0]
    before = "---\nname: work\ndescription: 開発依頼で使う\n---\n本文\n"
    after = "---\nname: work\ndescription: 開発依頼で使う\nallowed-tools: Bash(*)\n---\n本文\n"
    classification = classify_change(FileChange(changed, before, after))
    assert classification is not None
    skill = tmp_path / changed
    skill.parent.mkdir(parents=True)
    skill.write_text(after)
    record = AuthoringRecord(
        id="AUTH-5",
        target_kind="skill",
        target_paths=(changed,),
        risk=classification.risk,
        exploration={"evidence_refs": [f"file:{changed}"]},
        spec={"goal": "g", "inputs": "i", "boundaries": "b", "output": "o", "feedback": "f"},
        state=AuthoringState.COMPARED,
    )
    outcome = EvalRun("r", "t", "V0", {}, {}, (PASS_TRIAL,))
    trigger = TriggerRun(
        "t1", "claude", "work", (TriggerResult("PS-TP-01", "TRIGGER_POS", True, True),), "t"
    )

    decision = evaluate_gate(
        record,
        root=tmp_path,
        risk=classification.risk,
        lint_errors=[],
        baseline=outcome,
        candidate=outcome,
        triggers={"claude": trigger},
        required_hosts=["claude"],
        approval_ref=scenario["input"]["approval_ref"],
        candidate_digests={},
        current_digests={},
    )

    assert classification.risk is AuthoringRisk.HIGH_RISK
    assert decision.status is GateStatus.NEEDS_HUMAN
    assert "APPROVAL_REQUIRED" in decision.reasons
    assert "not_promoted" in scenario["expected"]["assertions"]


def test_compare_command_exits_nonzero_for_must_regression(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / ".harness" / "authoring" / "evals").mkdir(parents=True)
    (tmp_path / ".harness" / "config.toml").write_text('profile = "balanced"\n')
    baseline = EvalRun("eval-b", "t", "V0", {}, {}, (PASS_TRIAL,))
    candidate = EvalRun("eval-c", "t", "V0", {}, {}, (FAIL_TRIAL,))
    (tmp_path / ".harness/authoring/evals/eval-b.json").write_text(to_json(baseline))
    (tmp_path / ".harness/authoring/evals/eval-c.json").write_text(to_json(candidate))

    code = main(
        [
            "author",
            "compare",
            "--root",
            str(tmp_path),
            "--baseline",
            "eval-b",
            "--candidate",
            "eval-c",
        ]
    )

    assert code == 1
    assert "must_regressions: E01" in capsys.readouterr().out
