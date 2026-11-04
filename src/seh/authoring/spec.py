from __future__ import annotations

import json
import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import cast

from seh.authoring.classify import is_authoring_path
from seh.contracts import AuthoringRecord, AuthoringRisk, AuthoringState
from seh.contracts.schema import SchemaError, validate

REQUIRED_CONTRACT_KEYS = ("goal", "inputs", "boundaries", "output", "feedback")

_BEFORE_APPROVAL = frozenset(
    {
        AuthoringState.CLASSIFIED,
        AuthoringState.EXPLORED,
        AuthoringState.PLANNED,
        AuthoringState.AWAITING_APPROVAL,
        AuthoringState.REJECTED,
        AuthoringState.NEEDS_HUMAN,
    }
)


def _is_empty(value: object) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, tuple, dict)):
        return not value
    return False


def _evidence_exists(ref: object, root: Path) -> bool:
    if not isinstance(ref, str):
        return False
    if ref.startswith("file:"):
        resolved = (root / ref.removeprefix("file:")).resolve()
        return resolved.is_relative_to(root.resolve()) and resolved.exists()
    if ref.startswith("git:"):
        commit = ref.removeprefix("git:")
        if not commit or commit.startswith("-"):
            return False
        result = subprocess.run(
            ["git", "-C", str(root), "cat-file", "-e", f"{commit}^{{commit}}"],
            capture_output=True,
        )
        return result.returncode == 0
    return False


def _evidence_errors(exploration: Mapping[str, object], root: Path) -> list[str]:
    refs = exploration.get("evidence_refs")
    if not isinstance(refs, list) or not refs:
        return ["EVIDENCE_MISSING"]
    return [
        f"EVIDENCE_NOT_FOUND:{ref}"
        for ref in cast("list[object]", refs)
        if not _evidence_exists(ref, root)
    ]


def validate_record(record_json: Mapping[str, object], *, root: Path) -> list[str]:
    try:
        validate("authoring_record", dict(record_json))
    except SchemaError as e:
        return [f"SCHEMA_INVALID:{e}"]
    spec = cast("Mapping[str, object]", record_json["spec"])
    errors = [f"CONTRACT_MISSING:{k}" for k in REQUIRED_CONTRACT_KEYS if _is_empty(spec.get(k))]
    errors += _evidence_errors(cast("Mapping[str, object]", record_json["exploration"]), root)
    if (
        record_json["risk"] == AuthoringRisk.HIGH_RISK.value
        and AuthoringState(cast("str", record_json["state"])) not in _BEFORE_APPROVAL
        and _is_empty(record_json.get("approval_ref"))
    ):
        errors.append("APPROVAL_MISSING")
    paths = cast("list[str]", record_json["target_paths"])
    errors += [f"TARGET_NOT_AUTHORING_PATH:{p}" for p in paths if not is_authoring_path(p)]
    return errors


def load_record(path: Path) -> AuthoringRecord:
    data = cast("dict[str, object]", json.loads(path.read_text(encoding="utf-8")))
    validate("authoring_record", data)
    return AuthoringRecord(
        id=cast("str", data["id"]),
        target_kind=cast("str", data["target_kind"]),
        target_paths=tuple(cast("list[str]", data["target_paths"])),
        risk=AuthoringRisk(cast("str", data["risk"])),
        exploration=cast("Mapping[str, object]", data["exploration"]),
        spec=cast("Mapping[str, object]", data["spec"]),
        plan_ref=cast("str | None", data.get("plan_ref")),
        approval_ref=cast("str | None", data.get("approval_ref")),
        baseline_run_id=cast("str | None", data.get("baseline_run_id")),
        candidate_run_id=cast("str | None", data.get("candidate_run_id")),
        state=AuthoringState(cast("str", data["state"])),
    )
