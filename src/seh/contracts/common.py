from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


@dataclass(frozen=True)
class Evidence:
    uri: str
    sha256: str


class ResultStatus(StrEnum):
    OK = "OK"
    NOT_FOUND = "NOT_FOUND"
    UNSUPPORTED = "UNSUPPORTED"
    ERROR = "ERROR"


@dataclass(frozen=True)
class Result:
    """status で UNSUPPORTED と「空の OK」を区別する。data の空/None では判定しない。"""

    status: ResultStatus
    data: object | None = None
    evidence: tuple[Evidence, ...] = ()
    message: str | None = None

    @property
    def ok(self) -> bool:
        return self.status is ResultStatus.OK
