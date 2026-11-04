from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from fnmatch import fnmatchcase


@dataclass(frozen=True)
class ApprovalToken:
    id: str
    scope: tuple[str, ...]
    target_digest: str
    expires_at: datetime
    issued_by: str

    def __post_init__(self) -> None:
        if self.expires_at.tzinfo is None:
            raise ValueError("expires_at must be timezone-aware")

    def is_valid_for(self, scope_item: str, digest: str, now: datetime) -> bool:
        if now.tzinfo is None:
            raise ValueError("now must be timezone-aware")
        if now >= self.expires_at or digest != self.target_digest:
            return False
        return any(fnmatchcase(scope_item, pattern) for pattern in self.scope)
