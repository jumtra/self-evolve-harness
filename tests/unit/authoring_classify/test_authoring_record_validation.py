import json
import subprocess
from pathlib import Path

import pytest

from seh.authoring.spec import REQUIRED_CONTRACT_KEYS, load_record, validate_record
from seh.contracts import AuthoringRisk, AuthoringState
from seh.contracts.schema import SchemaError


def test_valid_record_has_no_errors(tmp_path: Path) -> None:
    (tmp_path / "SKILL.md").write_text("x", encoding="utf-8")
    record = {
        "id": "AUTH-1",
        "target_kind": "skill",
        "target_paths": [".claude/skills/work/SKILL.md"],
        "risk": "behavioral",
        "exploration": {"evidence_refs": ["file:SKILL.md"]},
        "spec": {
            "goal": "検証が起動する",
            "inputs": ["依頼文"],
            "boundaries": "他 Skill は変更しない",
            "output": "evidence-backed result",
            "feedback": ["seh eval run"],
        },
        "approval_ref": None,
        "state": "AWAITING_EVAL",
    }

    assert validate_record(record, root=tmp_path) == []


def test_required_contract_keys_are_the_five_fr057_keys() -> None:
    assert REQUIRED_CONTRACT_KEYS == ("goal", "inputs", "boundaries", "output", "feedback")


def test_missing_and_empty_contract_keys_are_reported(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_text("x", encoding="utf-8")
    record = {
        "id": "AUTH-1",
        "target_kind": "skill",
        "target_paths": [".claude/skills/work/SKILL.md"],
        "risk": "behavioral",
        "exploration": {"evidence_refs": ["file:a.md"]},
        "spec": {"goal": "g", "inputs": [], "boundaries": "  ", "output": "o"},
        "state": "PLANNED",
    }

    errors = validate_record(record, root=tmp_path)

    assert errors == [
        "CONTRACT_MISSING:inputs",
        "CONTRACT_MISSING:boundaries",
        "CONTRACT_MISSING:feedback",
    ]


def test_schema_violation_is_reported(tmp_path: Path) -> None:
    errors = validate_record({"id": "x"}, root=tmp_path)

    assert len(errors) == 1
    assert errors[0].startswith("SCHEMA_INVALID:")


def test_missing_file_evidence_and_empty_evidence_are_reported(tmp_path: Path) -> None:
    spec = {k: "v" for k in REQUIRED_CONTRACT_KEYS}
    base = {
        "id": "AUTH-1",
        "target_kind": "skill",
        "target_paths": ["CLAUDE.md"],
        "risk": "behavioral",
        "spec": spec,
        "state": "PLANNED",
    }

    missing = validate_record(
        {**base, "exploration": {"evidence_refs": ["file:nope.md", "file:../outside.md"]}},
        root=tmp_path,
    )
    empty = validate_record({**base, "exploration": {"evidence_refs": []}}, root=tmp_path)

    assert missing == ["EVIDENCE_NOT_FOUND:file:nope.md", "EVIDENCE_NOT_FOUND:file:../outside.md"]
    assert empty == ["EVIDENCE_MISSING"]


def test_git_evidence_is_checked_with_cat_file(tmp_path: Path) -> None:
    git = ["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false"]
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / "f.md").write_text("x", encoding="utf-8")
    subprocess.run([*git, "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run([*git, "commit", "-q", "-m", "c"], cwd=tmp_path, check=True)
    sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=tmp_path, check=True, capture_output=True, text=True
    ).stdout.strip()
    spec = {k: "v" for k in REQUIRED_CONTRACT_KEYS}
    record = {
        "id": "AUTH-1",
        "target_kind": "skill",
        "target_paths": ["CLAUDE.md"],
        "risk": "behavioral",
        "exploration": {"evidence_refs": [f"git:{sha}", "git:deadbeef", "git:--help", "web:x"]},
        "spec": spec,
        "state": "PLANNED",
    }

    errors = validate_record(record, root=tmp_path)

    assert errors == [
        "EVIDENCE_NOT_FOUND:git:deadbeef",
        "EVIDENCE_NOT_FOUND:git:--help",
        "EVIDENCE_NOT_FOUND:web:x",
    ]


def test_high_risk_after_approval_without_approval_ref_is_reported(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_text("x", encoding="utf-8")
    record = {
        "id": "AUTH-1",
        "target_kind": "instructions",
        "target_paths": ["CLAUDE.md"],
        "risk": "high_risk",
        "exploration": {"evidence_refs": ["file:a.md"]},
        "spec": {k: "v" for k in REQUIRED_CONTRACT_KEYS},
        "approval_ref": "",
        "state": "WRITTEN",
    }
    awaiting = {**record, "state": "AWAITING_APPROVAL"}
    approved = {**record, "approval_ref": "approvals/1.json"}

    assert validate_record(record, root=tmp_path) == ["APPROVAL_MISSING"]
    assert validate_record(awaiting, root=tmp_path) == []
    assert validate_record(approved, root=tmp_path) == []


def test_non_authoring_target_path_is_reported(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_text("x", encoding="utf-8")
    record = {
        "id": "AUTH-1",
        "target_kind": "skill",
        "target_paths": ["src/app.py", ".agents/skills/x/SKILL.md"],
        "risk": "behavioral",
        "exploration": {"evidence_refs": ["file:a.md"]},
        "spec": {k: "v" for k in REQUIRED_CONTRACT_KEYS},
        "state": "PLANNED",
    }

    assert validate_record(record, root=tmp_path) == ["TARGET_NOT_AUTHORING_PATH:src/app.py"]


def test_load_record_returns_typed_record(tmp_path: Path) -> None:
    path = tmp_path / "rec.json"
    path.write_text(
        json.dumps(
            {
                "id": "AUTH-1",
                "target_kind": "skill",
                "target_paths": [".claude/skills/work/SKILL.md"],
                "risk": "high_risk",
                "exploration": {},
                "spec": {},
                "state": "APPROVED",
                "approval_ref": "a",
            }
        ),
        encoding="utf-8",
    )

    record = load_record(path)

    assert record.id == "AUTH-1"
    assert record.risk is AuthoringRisk.HIGH_RISK
    assert record.state is AuthoringState.APPROVED
    assert record.target_paths == (".claude/skills/work/SKILL.md",)
    assert record.approval_ref == "a"


def test_load_record_rejects_schema_violation(tmp_path: Path) -> None:
    path = tmp_path / "rec.json"
    path.write_text('{"id": "x"}', encoding="utf-8")

    with pytest.raises(SchemaError):
        load_record(path)
