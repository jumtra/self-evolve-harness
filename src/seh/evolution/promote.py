"""Promote only an approved candidate with matching evaluation and baseline evidence."""

from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path

from seh.contracts import ApprovalToken
from seh.evals.report import compare
from seh.evolution.benchmark import BenchmarkResult, overlay_digest
from seh.evolution.propose import ProposalError, _check_path, _check_symlinks
from seh.ownership import Transaction


class PromotionError(ValueError):
    pass


def promote(
    root: Path,
    candidate_id: str,
    files: Mapping[str, bytes | None],
    evidence: BenchmarkResult,
    *,
    approval: ApprovalToken | None,
    now: datetime,
    authoring_record: str | None = None,
) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_-]+", candidate_id) or not files:
        raise PromotionError("invalid or empty candidate")
    try:
        for path in files:
            _check_path(path)
            _check_symlinks(root, path)
    except ProposalError as exc:
        raise PromotionError(str(exc)) from exc
    from seh.evolution.authoring_guard import check_authoring_gate

    try:
        check_authoring_gate(root, dict(files), authoring_record)
    except (OSError, ValueError, KeyError) as exc:
        raise PromotionError(str(exc)) from exc
    digest = overlay_digest(files)
    if (
        approval is None
        or approval.issued_by != "human"
        or not approval.is_valid_for(f"evolve:promote:{candidate_id}", digest, now)
    ):
        raise PromotionError("human approval for candidate digest is required")
    if evidence.candidate_digest != digest or not evidence.baseline_digest:
        raise PromotionError("benchmark does not match candidate")
    current = {
        path: (root / path).read_bytes() if (root / path).is_file() else None for path in files
    }
    if overlay_digest(current) != evidence.baseline_digest:
        raise PromotionError("baseline changed since benchmark")
    candidate = evidence.candidate.trials
    baseline = evidence.baseline.trials
    if (
        not candidate
        or not baseline
        or not {"training", "regression", "holdout"}.issubset({t.split for t in candidate})
        or not {"training", "regression", "holdout"}.issubset({t.split for t in baseline})
    ):
        raise PromotionError("benchmark is incomplete")
    if Counter((t.case_id, t.split, t.trial) for t in baseline) != Counter(
        (t.case_id, t.split, t.trial) for t in candidate
    ):
        raise PromotionError("benchmark trials do not match")
    comparison = compare(evidence.baseline, evidence.candidate)
    if (
        not comparison.promotable
        or not comparison.improved
        or comparison.regressed
        or any(
            t.verdict_status != "PASS" for t in candidate if t.split in {"regression", "holdout"}
        )
    ):
        raise PromotionError("benchmark does not satisfy promotion gates")
    if any(not t.evidence_refs for t in candidate):
        raise PromotionError("BENCHMARK_EVIDENCE_UNVERIFIED: isolated evaluation evidence required")
    with Transaction(root) as tx:
        for path, content in sorted(files.items()):
            if content is None:
                tx.delete(path)
            else:
                tx.write(path, content)
        record = {
            "candidate_id": candidate_id,
            "snapshot_id": tx.snapshot_id,
            "candidate_digest": digest,
            "evidence_refs": sorted({ref for trial in candidate for ref in trial.evidence_refs}),
            "paths": list(sorted(files)),
            "at": now.isoformat(),
        }
        tx.write(
            f".harness/evolution/promotions/{tx.snapshot_id}.json",
            (json.dumps(record) + "\n").encode(),
        )
    return tx.snapshot_id
