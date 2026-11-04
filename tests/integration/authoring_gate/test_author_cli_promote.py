import builtins
import hashlib
import json
import sys
from pathlib import Path

import pytest

from seh.authoring.eval import TriggerResult, TriggerRun, trigger_run_to_json
from seh.cli import main
from seh.evals.report import to_json
from seh.evals.runner import EvalRun, TrialResult

PASS_TRIAL = TrialResult("E01", "regression", 0, "PASS", 1, 0, 0, 1.0, 1, 1, 0.0, None, ())
FAIL_TRIAL = TrialResult("E01", "regression", 0, "FAIL", 1, 0, 0, 1.0, 1, 1, 0.0, None, ())


CONTRACT = "## Goal\na\n## Inputs\nb\n## Boundaries\nc\n## Output\nd\n## Feedback\ne\n"
OLD = "---\ndescription: 開発依頼で使う\n---\n" + CONTRACT
NEW = OLD + "追記\n"
REGRESSING = OLD + "回帰する変更\n"


class _Tty:
    def isatty(self) -> bool:
        return True


def test_behavioral_candidate_with_full_evidence_is_promoted_and_rolled_back(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    harness = tmp_path / ".harness"
    (harness / "authoring" / "evals").mkdir(parents=True)
    (harness / "authoring" / "candidates" / "AUTH-1" / "skills" / "work").mkdir(parents=True)
    (harness / "spec" / "skills" / "work").mkdir(parents=True)
    (harness / "spec" / "instructions").mkdir(parents=True)
    (harness / "spec" / "instructions" / "core.md").write_text("共通方針\n")
    (harness / "config.toml").write_text('profile = "balanced"\n')
    (harness / "spec" / "skills" / "work" / "SKILL.md").write_text(OLD)
    (harness / "authoring" / "candidates" / "AUTH-1" / "skills" / "work" / "SKILL.md").write_text(
        NEW
    )
    digest = hashlib.sha256(NEW.encode()).hexdigest()
    skill = tmp_path / ".claude" / "skills" / "work" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("x")
    baseline = EvalRun("eval-b", "t", "V0", {}, {}, (PASS_TRIAL,))
    candidate = EvalRun(
        "eval-c", "t", "V0", {"file:skills/work/SKILL.md": digest}, {}, (PASS_TRIAL,)
    )
    (harness / "authoring" / "evals" / "eval-b.json").write_text(to_json(baseline))
    (harness / "authoring" / "evals" / "eval-c.json").write_text(to_json(candidate))
    trigger = TriggerRun(
        "trigger-AUTH-1-claude-1",
        "claude",
        "work",
        (
            TriggerResult("PS-TP-01", "TRIGGER_POS", True, True),
            TriggerResult("PS-TN-01", "TRIGGER_NEG", False, False),
        ),
        "2026-11-04T00:00:00+00:00",
    )
    (harness / "authoring" / "evals" / "trigger-AUTH-1-claude-1.json").write_text(
        json.dumps({**json.loads(trigger_run_to_json(trigger)), "record_id": "AUTH-1"})
    )
    record_file = harness / "authoring" / "AUTH-1.json"
    record_file.write_text(
        json.dumps(
            {
                "id": "AUTH-1",
                "target_kind": "skill",
                "target_paths": [".harness/spec/skills/work/SKILL.md"],
                "risk": "behavioral",
                "exploration": {"evidence_refs": ["file:.claude/skills/work/SKILL.md"]},
                "spec": {
                    "goal": "g",
                    "inputs": "i",
                    "boundaries": "b",
                    "output": "o",
                    "feedback": "f",
                },
                "baseline_run_id": "eval-b",
                "candidate_run_id": "eval-c",
                "state": "PLANNED",
            }
        )
    )

    promote_code = main(
        ["author", "promote", "--root", str(tmp_path), "--record", str(record_file)]
    )
    promote_out = capsys.readouterr().out
    promoted_text = (harness / "spec" / "skills" / "work" / "SKILL.md").read_text()
    promotion_id = json.loads((harness / "authoring" / "promotions.jsonl").read_text())[
        "promotion_id"
    ]
    rollback_code = main(
        ["author", "rollback", "--root", str(tmp_path), "--promotion", promotion_id]
    )

    assert promote_code == 0
    assert "gate: PASS" in promote_out
    assert "seh sync" in promote_out
    assert promoted_text == NEW
    assert rollback_code == 0
    assert (harness / "spec" / "skills" / "work" / "SKILL.md").read_text() == OLD
    assert json.loads(record_file.read_text())["state"] == "ROLLED_BACK"


def test_high_risk_promote_without_tty_is_refused_and_keeps_original(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    harness = tmp_path / ".harness"
    (harness / "authoring" / "evals").mkdir(parents=True)
    (harness / "authoring" / "candidates" / "AUTH-H" / "skills" / "work").mkdir(parents=True)
    (harness / "spec" / "skills" / "work").mkdir(parents=True)
    (harness / "spec" / "instructions").mkdir(parents=True)
    (harness / "spec" / "instructions" / "core.md").write_text("共通方針\n")
    (harness / "config.toml").write_text('profile = "balanced"\n')
    (harness / "spec" / "skills" / "work" / "SKILL.md").write_text(OLD)
    (harness / "authoring" / "candidates" / "AUTH-H" / "skills" / "work" / "SKILL.md").write_text(
        NEW
    )
    digest = hashlib.sha256(NEW.encode()).hexdigest()
    skill = tmp_path / ".claude" / "skills" / "work" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("x")
    baseline = EvalRun("eval-b", "t", "V0", {}, {}, (PASS_TRIAL,))
    candidate = EvalRun(
        "eval-c", "t", "V0", {"file:skills/work/SKILL.md": digest}, {}, (PASS_TRIAL,)
    )
    (harness / "authoring" / "evals" / "eval-b.json").write_text(to_json(baseline))
    (harness / "authoring" / "evals" / "eval-c.json").write_text(to_json(candidate))
    trigger = TriggerRun(
        "trigger-AUTH-H-claude-1",
        "claude",
        "work",
        (TriggerResult("PS-TP-01", "TRIGGER_POS", True, True),),
        "2026-11-04T00:00:00+00:00",
    )
    (harness / "authoring" / "evals" / "trigger-AUTH-H-claude-1.json").write_text(
        json.dumps({**json.loads(trigger_run_to_json(trigger)), "record_id": "AUTH-H"})
    )
    record_file = harness / "authoring" / "AUTH-H.json"
    record_file.write_text(
        json.dumps(
            {
                "id": "AUTH-H",
                "target_kind": "skill",
                "target_paths": [".harness/spec/skills/work/SKILL.md"],
                "risk": "high_risk",
                "exploration": {"evidence_refs": ["file:.claude/skills/work/SKILL.md"]},
                "spec": {
                    "goal": "g",
                    "inputs": "i",
                    "boundaries": "b",
                    "output": "o",
                    "feedback": "f",
                },
                "baseline_run_id": "eval-b",
                "candidate_run_id": "eval-c",
                "state": "AWAITING_APPROVAL",
            }
        )
    )

    code = main(["author", "promote", "--root", str(tmp_path), "--record", str(record_file)])

    captured = capsys.readouterr()
    assert code == 1
    assert "NEEDS_HUMAN" in captured.out
    assert (harness / "spec" / "skills" / "work" / "SKILL.md").read_text() == OLD
    assert json.loads(record_file.read_text()).get("approval_ref") is None


def test_high_risk_promote_with_interactive_yes_records_human_approval(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness = tmp_path / ".harness"
    (harness / "authoring" / "evals").mkdir(parents=True)
    (harness / "authoring" / "candidates" / "AUTH-H" / "skills" / "work").mkdir(parents=True)
    (harness / "spec" / "skills" / "work").mkdir(parents=True)
    (harness / "spec" / "instructions").mkdir(parents=True)
    (harness / "spec" / "instructions" / "core.md").write_text("共通方針\n")
    (harness / "config.toml").write_text('profile = "balanced"\n')
    (harness / "spec" / "skills" / "work" / "SKILL.md").write_text(OLD)
    (harness / "authoring" / "candidates" / "AUTH-H" / "skills" / "work" / "SKILL.md").write_text(
        NEW
    )
    digest = hashlib.sha256(NEW.encode()).hexdigest()
    skill = tmp_path / ".claude" / "skills" / "work" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("x")
    baseline = EvalRun("eval-b", "t", "V0", {}, {}, (PASS_TRIAL,))
    candidate = EvalRun(
        "eval-c", "t", "V0", {"file:skills/work/SKILL.md": digest}, {}, (PASS_TRIAL,)
    )
    (harness / "authoring" / "evals" / "eval-b.json").write_text(to_json(baseline))
    (harness / "authoring" / "evals" / "eval-c.json").write_text(to_json(candidate))
    trigger = TriggerRun(
        "trigger-AUTH-H-claude-1",
        "claude",
        "work",
        (TriggerResult("PS-TP-01", "TRIGGER_POS", True, True),),
        "2026-11-04T00:00:00+00:00",
    )
    (harness / "authoring" / "evals" / "trigger-AUTH-H-claude-1.json").write_text(
        json.dumps({**json.loads(trigger_run_to_json(trigger)), "record_id": "AUTH-H"})
    )
    record_file = harness / "authoring" / "AUTH-H.json"
    record_file.write_text(
        json.dumps(
            {
                "id": "AUTH-H",
                "target_kind": "skill",
                "target_paths": [".harness/spec/skills/work/SKILL.md"],
                "risk": "high_risk",
                "exploration": {"evidence_refs": ["file:.claude/skills/work/SKILL.md"]},
                "spec": {
                    "goal": "g",
                    "inputs": "i",
                    "boundaries": "b",
                    "output": "o",
                    "feedback": "f",
                },
                "baseline_run_id": "eval-b",
                "candidate_run_id": "eval-c",
                "state": "AWAITING_APPROVAL",
            }
        )
    )
    monkeypatch.setattr(sys, "stdin", _Tty())
    monkeypatch.setattr(builtins, "input", lambda _prompt="": "y")

    code = main(["author", "promote", "--root", str(tmp_path), "--record", str(record_file)])

    saved = json.loads(record_file.read_text())
    assert code == 0
    assert saved["state"] == "PROMOTED"
    assert saved["approval_ref"].startswith("human-tty:")
    assert (harness / "spec" / "skills" / "work" / "SKILL.md").read_text() == NEW


def test_high_risk_promote_with_interactive_no_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness = tmp_path / ".harness"
    (harness / "authoring" / "evals").mkdir(parents=True)
    (harness / "authoring" / "candidates" / "AUTH-H" / "skills" / "work").mkdir(parents=True)
    (harness / "spec" / "skills" / "work").mkdir(parents=True)
    (harness / "spec" / "instructions").mkdir(parents=True)
    (harness / "spec" / "instructions" / "core.md").write_text("共通方針\n")
    (harness / "config.toml").write_text('profile = "balanced"\n')
    (harness / "spec" / "skills" / "work" / "SKILL.md").write_text(OLD)
    (harness / "authoring" / "candidates" / "AUTH-H" / "skills" / "work" / "SKILL.md").write_text(
        NEW
    )
    digest = hashlib.sha256(NEW.encode()).hexdigest()
    skill = tmp_path / ".claude" / "skills" / "work" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("x")
    baseline = EvalRun("eval-b", "t", "V0", {}, {}, (PASS_TRIAL,))
    candidate = EvalRun(
        "eval-c", "t", "V0", {"file:skills/work/SKILL.md": digest}, {}, (PASS_TRIAL,)
    )
    (harness / "authoring" / "evals" / "eval-b.json").write_text(to_json(baseline))
    (harness / "authoring" / "evals" / "eval-c.json").write_text(to_json(candidate))
    trigger = TriggerRun(
        "trigger-AUTH-H-claude-1",
        "claude",
        "work",
        (TriggerResult("PS-TP-01", "TRIGGER_POS", True, True),),
        "2026-11-04T00:00:00+00:00",
    )
    (harness / "authoring" / "evals" / "trigger-AUTH-H-claude-1.json").write_text(
        json.dumps({**json.loads(trigger_run_to_json(trigger)), "record_id": "AUTH-H"})
    )
    record_file = harness / "authoring" / "AUTH-H.json"
    record_file.write_text(
        json.dumps(
            {
                "id": "AUTH-H",
                "target_kind": "skill",
                "target_paths": [".harness/spec/skills/work/SKILL.md"],
                "risk": "high_risk",
                "exploration": {"evidence_refs": ["file:.claude/skills/work/SKILL.md"]},
                "spec": {
                    "goal": "g",
                    "inputs": "i",
                    "boundaries": "b",
                    "output": "o",
                    "feedback": "f",
                },
                "baseline_run_id": "eval-b",
                "candidate_run_id": "eval-c",
                "state": "AWAITING_APPROVAL",
            }
        )
    )
    monkeypatch.setattr(sys, "stdin", _Tty())
    monkeypatch.setattr(builtins, "input", lambda _prompt="": "n")

    code = main(["author", "promote", "--root", str(tmp_path), "--record", str(record_file)])

    assert code == 1
    assert (harness / "spec" / "skills" / "work" / "SKILL.md").read_text() == OLD


def test_regressing_candidate_is_not_promoted_and_original_remains_a08(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    scenario = json.loads(
        Path("tests/fixtures/prompt_skill/authoring/A08.json").read_text(encoding="utf-8")
    )
    harness = tmp_path / ".harness"
    (harness / "authoring" / "evals").mkdir(parents=True)
    (harness / "authoring" / "candidates" / "AUTH-R" / "skills" / "work").mkdir(parents=True)
    (harness / "spec" / "skills" / "work").mkdir(parents=True)
    (harness / "spec" / "instructions").mkdir(parents=True)
    (harness / "spec" / "instructions" / "core.md").write_text("共通方針\n")
    (harness / "config.toml").write_text('profile = "balanced"\n')
    (harness / "spec" / "skills" / "work" / "SKILL.md").write_text(OLD)
    (harness / "authoring" / "candidates" / "AUTH-R" / "skills" / "work" / "SKILL.md").write_text(
        REGRESSING
    )
    digest = hashlib.sha256(REGRESSING.encode()).hexdigest()
    skill = tmp_path / ".claude" / "skills" / "work" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("x")
    baseline = EvalRun("eval-b", "t", "V0", {}, {}, (PASS_TRIAL,))
    candidate = EvalRun(
        "eval-c", "t", "V0", {"file:skills/work/SKILL.md": digest}, {}, (FAIL_TRIAL,)
    )
    (harness / "authoring" / "evals" / "eval-b.json").write_text(to_json(baseline))
    (harness / "authoring" / "evals" / "eval-c.json").write_text(to_json(candidate))
    trigger = TriggerRun(
        "trigger-AUTH-R-claude-1",
        "claude",
        "work",
        (TriggerResult("PS-TP-01", "TRIGGER_POS", True, True),),
        "2026-11-04T00:00:00+00:00",
    )
    (harness / "authoring" / "evals" / "trigger-AUTH-R-claude-1.json").write_text(
        json.dumps({**json.loads(trigger_run_to_json(trigger)), "record_id": "AUTH-R"})
    )
    record_file = harness / "authoring" / "AUTH-R.json"
    record_file.write_text(
        json.dumps(
            {
                "id": "AUTH-R",
                "target_kind": "skill",
                "target_paths": [".harness/spec/skills/work/SKILL.md"],
                "risk": "behavioral",
                "exploration": {"evidence_refs": ["file:.claude/skills/work/SKILL.md"]},
                "spec": {
                    "goal": "g",
                    "inputs": "i",
                    "boundaries": "b",
                    "output": "o",
                    "feedback": "f",
                },
                "baseline_run_id": "eval-b",
                "candidate_run_id": "eval-c",
                "state": "PLANNED",
            }
        )
    )

    code = main(["author", "promote", "--root", str(tmp_path), "--record", str(record_file)])

    assert scenario["expected"]["state"] == "NOT_PROMOTED_ROLLBACK_AVAILABLE"
    assert code == 1
    assert "MUST_REGRESSION" in capsys.readouterr().out
    assert (harness / "spec" / "skills" / "work" / "SKILL.md").read_text() == OLD
    assert not (harness / "authoring" / "promotions.jsonl").exists()
    assert json.loads(record_file.read_text())["state"] == "PLANNED"


def test_promote_without_any_eval_is_blocked_no_eval_a07(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    scenario = json.loads(
        Path("tests/fixtures/prompt_skill/authoring/A07.json").read_text(encoding="utf-8")
    )
    harness = tmp_path / ".harness"
    (harness / "authoring").mkdir(parents=True)
    (harness / "spec" / "skills" / "work").mkdir(parents=True)
    (harness / "spec" / "instructions").mkdir(parents=True)
    (harness / "spec" / "instructions" / "core.md").write_text("共通方針\n")
    (harness / "config.toml").write_text('profile = "balanced"\n')
    (harness / "spec" / "skills" / "work" / "SKILL.md").write_text(OLD)
    skill = tmp_path / ".claude" / "skills" / "work" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("x")
    record_file = harness / "authoring" / "AUTH-A.json"
    record_file.write_text(
        json.dumps(
            {
                "id": "AUTH-A",
                "target_kind": "skill",
                "target_paths": [".harness/spec/skills/work/SKILL.md"],
                "risk": "behavioral",
                "exploration": {"evidence_refs": ["file:.claude/skills/work/SKILL.md"]},
                "spec": {
                    "goal": "g",
                    "inputs": "i",
                    "boundaries": "b",
                    "output": "o",
                    "feedback": "f",
                },
                "state": "PLANNED",
            }
        )
    )

    code = main(["author", "promote", "--root", str(tmp_path), "--record", str(record_file)])

    out = capsys.readouterr().out
    assert scenario["expected"]["state"] == "BLOCKED_NO_EVAL"
    assert code == 1
    assert "gate: BLOCKED_NO_EVAL" in out
    assert "NO_FRESH_EVAL:claude" in out
    assert "gate: PASS" not in out
