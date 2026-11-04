"""Write approved learning to the knowledge store for subsequent splitting."""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

from seh.knowledge import VerifiedConstraint, append_constraint


def record_learning(
    root: Path,
    *,
    id: str,
    statement: str,
    scope_globs: tuple[str, ...],
    source_record: str,
    evidence_refs: tuple[str, ...],
    now: datetime,
    expires_at: datetime | None = None,
) -> VerifiedConstraint:
    if (
        not re.fullmatch(r"[A-Za-z0-9_-]+", source_record)
        or not id
        or not statement.strip()
        or not scope_globs
        or not evidence_refs
        or now.tzinfo is None
    ):
        raise ValueError("learning requires a source, statement, scope, evidence and timezone")
    if expires_at is not None and (expires_at.tzinfo is None or expires_at <= now):
        raise ValueError("expires_at must be in the future")
    record = root / ".harness/evolution/promotions" / f"{source_record}.json"
    if (
        not record.is_file()
        or record.is_symlink()
        or json.loads(record.read_text()).get("snapshot_id") != source_record
    ):
        raise ValueError("learning requires an existing promotion")
    metadata = json.loads(record.read_text())
    if not set(evidence_refs).issubset(set(metadata.get("evidence_refs", []))):
        raise ValueError("learning evidence does not match promotion")
    constraint = VerifiedConstraint(
        id,
        statement,
        scope_globs,
        source_record,
        evidence_refs,
        now.isoformat(),
        expires_at.isoformat() if expires_at else None,
        "active",
    )
    append_constraint(root, constraint)
    return constraint
