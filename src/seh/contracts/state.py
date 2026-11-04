from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum


class UnitState(StrEnum):
    PENDING = "PENDING"
    READY = "READY"
    RUNNING = "RUNNING"
    VERIFYING = "VERIFYING"
    REPAIRING = "REPAIRING"
    PASSED = "PASSED"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"
    CANCELLED = "CANCELLED"
    WAITING_APPROVAL = "WAITING_APPROVAL"


class InvalidTransition(ValueError):
    pass


_S = UnitState

# RUNNING から PASSED へは直接行けない。必ず VERIFYING を経由して再検証する（02 §5.3）。
# 承認待ちからの再開も PASSED へ直行させず VERIFYING で再検証する。
ALLOWED_TRANSITIONS: Mapping[UnitState, frozenset[UnitState]] = {
    _S.PENDING: frozenset({_S.READY, _S.BLOCKED, _S.CANCELLED}),
    _S.READY: frozenset({_S.RUNNING, _S.WAITING_APPROVAL, _S.BLOCKED, _S.CANCELLED}),
    _S.RUNNING: frozenset({_S.VERIFYING, _S.WAITING_APPROVAL, _S.FAILED, _S.BLOCKED, _S.CANCELLED}),
    _S.VERIFYING: frozenset(
        {_S.PASSED, _S.REPAIRING, _S.FAILED, _S.WAITING_APPROVAL, _S.BLOCKED, _S.CANCELLED}
    ),
    _S.REPAIRING: frozenset({_S.RUNNING, _S.WAITING_APPROVAL, _S.FAILED, _S.BLOCKED, _S.CANCELLED}),
    _S.WAITING_APPROVAL: frozenset({_S.READY, _S.VERIFYING, _S.FAILED, _S.BLOCKED, _S.CANCELLED}),
    _S.BLOCKED: frozenset({_S.READY, _S.FAILED, _S.CANCELLED}),
    _S.PASSED: frozenset(),
    _S.FAILED: frozenset(),
    _S.CANCELLED: frozenset(),
}


def transition(current: UnitState, nxt: UnitState) -> UnitState:
    if nxt not in ALLOWED_TRANSITIONS[current]:
        raise InvalidTransition(f"{current.value} -> {nxt.value} is not allowed")
    return nxt
