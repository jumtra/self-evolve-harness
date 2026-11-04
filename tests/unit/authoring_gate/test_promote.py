import json
from pathlib import Path

import pytest

from seh.authoring.gate import GateDecision, GateStatus
from seh.authoring.promote import PromotionRefused, promote, rollback_promotion
from seh.contracts import AuthoringRecord, AuthoringRisk, AuthoringState


def test_promote_writes_spec_logs_promotion_and_marks_record_promoted(tmp_path: Path) -> None:
    spec_file = tmp_path / ".harness" / "spec" / "skills" / "work" / "SKILL.md"
    spec_file.parent.mkdir(parents=True)
    spec_file.write_text("old")
    candidate = tmp_path / "cand"
    (candidate / "skills" / "work").mkdir(parents=True)
    (candidate / "skills" / "work" / "SKILL.md").write_text("new")
    record = AuthoringRecord(
        id="AUTH-1",
        target_kind="skill",
        target_paths=(".harness/spec/skills/work/SKILL.md",),
        risk=AuthoringRisk.BEHAVIORAL,
        exploration={"evidence_refs": ["file:x"]},
        spec={"goal": "g"},
        state=AuthoringState.PLANNED,
    )

    promotion_id = promote(
        tmp_path, record, GateDecision(GateStatus.PASS, ()), candidate_dir=candidate
    )

    assert spec_file.read_text() == "new"
    lines = (tmp_path / ".harness/authoring/promotions.jsonl").read_text().splitlines()
    entry = json.loads(lines[0])
    assert entry["promotion_id"] == promotion_id
    assert entry["record_id"] == "AUTH-1"
    assert entry["files"] == [".harness/spec/skills/work/SKILL.md"]
    saved = json.loads((tmp_path / ".harness/authoring/AUTH-1.json").read_text())
    assert saved["state"] == "PROMOTED"


@pytest.mark.parametrize(
    "status", [GateStatus.FAIL, GateStatus.BLOCKED_NO_EVAL, GateStatus.NEEDS_HUMAN]
)
def test_promote_refuses_non_pass_and_keeps_original(tmp_path: Path, status: GateStatus) -> None:
    spec_file = tmp_path / ".harness" / "spec" / "skills" / "work" / "SKILL.md"
    spec_file.parent.mkdir(parents=True)
    spec_file.write_text("old")
    candidate = tmp_path / "cand" / "skills" / "work"
    candidate.mkdir(parents=True)
    (candidate / "SKILL.md").write_text("new")
    record = AuthoringRecord(
        id="AUTH-1",
        target_kind="skill",
        target_paths=(".harness/spec/skills/work/SKILL.md",),
        risk=AuthoringRisk.BEHAVIORAL,
        exploration={},
        spec={},
        state=AuthoringState.COMPARED,
    )

    with pytest.raises(PromotionRefused):
        promote(
            tmp_path,
            record,
            GateDecision(status, ("X",)),
            candidate_dir=tmp_path / "cand",
        )

    assert spec_file.read_text() == "old"
    assert not (tmp_path / ".harness/authoring/promotions.jsonl").exists()


def test_rollback_restores_original_and_marks_record_rolled_back(tmp_path: Path) -> None:
    spec_file = tmp_path / ".harness" / "spec" / "skills" / "work" / "SKILL.md"
    spec_file.parent.mkdir(parents=True)
    spec_file.write_text("old")
    (tmp_path / "cand" / "skills" / "work").mkdir(parents=True)
    (tmp_path / "cand" / "skills" / "work" / "SKILL.md").write_text("new")
    record = AuthoringRecord(
        id="AUTH-1",
        target_kind="skill",
        target_paths=(".harness/spec/skills/work/SKILL.md",),
        risk=AuthoringRisk.BEHAVIORAL,
        exploration={"evidence_refs": ["file:x"]},
        spec={"goal": "g"},
        state=AuthoringState.PLANNED,
    )
    promotion_id = promote(
        tmp_path, record, GateDecision(GateStatus.PASS, ()), candidate_dir=tmp_path / "cand"
    )

    restored = rollback_promotion(tmp_path, promotion_id)

    assert restored == [".harness/spec/skills/work/SKILL.md"]
    assert spec_file.read_text() == "old"
    saved = json.loads((tmp_path / ".harness/authoring/AUTH-1.json").read_text())
    assert saved["state"] == "ROLLED_BACK"


def test_rollback_unknown_promotion_raises(tmp_path: Path) -> None:
    with pytest.raises(KeyError):
        rollback_promotion(tmp_path, "20260101T000000Z-aaaaaa")
