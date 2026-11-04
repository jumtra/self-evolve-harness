"""昇格判定（04 §6.3 の不変条件）。評価できないときは BLOCKED_NO_EVAL / NEEDS_HUMAN に倒す。"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from enum import StrEnum
from pathlib import Path

from seh.authoring.eval import TriggerRun
from seh.authoring.spec import validate_record
from seh.contracts import AuthoringRecord, AuthoringRisk, Diagnostic
from seh.evals.report import compare
from seh.evals.runner import EvalRun
from seh.ownership import OwnershipManifest

SPEC_PREFIX = ".harness/spec/"


class GateStatus(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    BLOCKED_NO_EVAL = "BLOCKED_NO_EVAL"
    NEEDS_HUMAN = "NEEDS_HUMAN"
    NOT_CONFIGURED = "NOT_CONFIGURED"


@dataclass(frozen=True)
class GateDecision:
    status: GateStatus
    reasons: tuple[str, ...]


# 複数の失敗が重なったときの採用順。FAIL が最も強く、人間確認が評価待ちに優先する
_SEVERITY = (GateStatus.FAIL, GateStatus.NEEDS_HUMAN, GateStatus.BLOCKED_NO_EVAL)


def record_to_json(record: AuthoringRecord) -> dict[str, object]:
    return {
        "id": record.id,
        "target_kind": record.target_kind,
        "target_paths": list(record.target_paths),
        "risk": record.risk.value,
        "exploration": dict(record.exploration),
        "spec": dict(record.spec),
        "plan_ref": record.plan_ref,
        "approval_ref": record.approval_ref,
        "baseline_run_id": record.baseline_run_id,
        "candidate_run_id": record.candidate_run_id,
        "state": record.state.value,
    }


def file_digests(directory: Path) -> dict[str, str]:
    if not directory.is_dir():
        return {}
    return {
        p.relative_to(directory).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(directory.rglob("*"))
        if p.is_file()
    }


def is_initial_generation(root: Path, path: str) -> bool:
    """D13: `seh init --apply` 生成後に未変更のファイルは Authoring Gate の対象外。"""
    if not path.startswith(SPEC_PREFIX):
        return False
    entry = OwnershipManifest.load(root).get(path)
    target = root / path
    if entry is None or entry.generator != "init" or not target.is_file():
        return False
    return hashlib.sha256(target.read_bytes()).hexdigest() == entry.sha256


def _trigger_reasons(
    triggers: Mapping[str, TriggerRun], required_hosts: Sequence[str]
) -> tuple[list[str], list[str]]:
    blocked: list[str] = []
    mismatched: list[str] = []
    for host in required_hosts:
        run = triggers.get(host)
        if run is None or not run.results or any(r.observed is None for r in run.results):
            blocked.append(f"NO_FRESH_EVAL:{host}")
            continue
        mismatched += [
            f"TRIGGER_MISMATCH:{r.case_id}"
            for r in run.results
            if r.observed is not None and r.observed != r.expected_trigger
        ]
    return blocked, mismatched


def evaluate_gate(
    record: AuthoringRecord,
    *,
    root: Path,
    risk: AuthoringRisk,
    lint_errors: Sequence[Diagnostic],
    baseline: EvalRun | None,
    candidate: EvalRun | None,
    triggers: Mapping[str, TriggerRun],
    required_hosts: Sequence[str],
    approval_ref: str | None,
    candidate_digests: Mapping[str, str],
    current_digests: Mapping[str, str],
) -> GateDecision:
    found: list[tuple[GateStatus, str]] = []
    effective_approval = approval_ref or record.approval_ref
    # 承認欠落は schema 不備ではなく人間確認待ち（NEEDS_HUMAN）として扱う
    schema_errors = validate_record(
        record_to_json(replace(record, approval_ref=effective_approval)), root=root
    )
    found += [(GateStatus.FAIL, e) for e in schema_errors if e != "APPROVAL_MISSING"]
    found += [(GateStatus.FAIL, f"LINT_ERROR:{d.code}") for d in lint_errors]
    if risk is AuthoringRisk.HIGH_RISK and not effective_approval:
        found.append((GateStatus.NEEDS_HUMAN, "APPROVAL_REQUIRED"))
    if risk is not AuthoringRisk.TEXT_ONLY:
        blocked, mismatched = _trigger_reasons(triggers, required_hosts)
        if candidate is None:
            found.append((GateStatus.BLOCKED_NO_EVAL, "NO_FRESH_EVAL:outcome"))
        found += [(GateStatus.BLOCKED_NO_EVAL, r) for r in blocked]
        if baseline is None:
            found.append((GateStatus.BLOCKED_NO_EVAL, "NO_BASELINE"))
        elif candidate is not None and not compare(baseline, candidate).promotable:
            found.append((GateStatus.FAIL, "MUST_REGRESSION"))
        found += [(GateStatus.FAIL, r) for r in mismatched]
    if dict(candidate_digests) != dict(current_digests):
        found.append((GateStatus.FAIL, "CANDIDATE_CHANGED_AFTER_EVAL"))
    reasons = tuple(reason for _, reason in found)
    statuses = {status for status, _ in found}
    status = next((s for s in _SEVERITY if s in statuses), GateStatus.PASS)
    return GateDecision(status, reasons)
