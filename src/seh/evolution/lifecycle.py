"""Identify stale generated candidates without deleting user-authored knowledge."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Literal


@dataclass(frozen=True)
class CandidateRecord:
    id: str
    status: Literal["proposed", "failed", "stalled", "promoted", "retired"]
    updated_at: datetime
    generated: bool


def retire_stale(
    records: list[CandidateRecord], *, now: datetime, max_age: timedelta
) -> list[CandidateRecord]:
    if now.tzinfo is None or max_age <= timedelta(0):
        raise ValueError("timezone-aware now and positive max_age required")
    return [
        replace(record, status="retired")
        if record.generated
        and record.status in {"proposed", "failed", "stalled"}
        and now - record.updated_at >= max_age
        else record
        for record in records
    ]
