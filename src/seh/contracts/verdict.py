from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from seh.contracts.common import Evidence


class VerdictStatus(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True)
class Verdict:
    node_id: str
    status: VerdictStatus
    check_id: str
    reason_code: str
    evidence: tuple[Evidence, ...]
    allowed_repair_scope: tuple[str, ...]
    attempt: int
    max_attempts: int

    @property
    def passed(self) -> bool:
        return self.status is VerdictStatus.PASS

    def as_repair_input(self) -> dict[str, object]:
        return {
            "failed_check": self.check_id,
            "reason": self.reason_code,
            "evidence": [e.uri for e in self.evidence],
            "allowed_scope": list(self.allowed_repair_scope),
        }
