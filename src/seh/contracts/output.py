from __future__ import annotations

from dataclasses import dataclass

from seh.contracts.state import UnitState


@dataclass(frozen=True)
class FinalOutput:
    task_id: str
    status: UnitState
    summary: str
    changed_files: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    remaining_risks: tuple[str, ...]
    requires_human_approval: bool
