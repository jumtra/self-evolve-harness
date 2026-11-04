from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from enum import StrEnum


class AuthoringRisk(StrEnum):
    TEXT_ONLY = "text_only"
    BEHAVIORAL = "behavioral"
    HIGH_RISK = "high_risk"


class AuthoringState(StrEnum):
    CLASSIFIED = "CLASSIFIED"
    EXPLORED = "EXPLORED"
    PLANNED = "PLANNED"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    APPROVED = "APPROVED"
    BASELINED = "BASELINED"
    WRITTEN = "WRITTEN"
    VERIFYING = "VERIFYING"
    REPAIRING = "REPAIRING"
    COMPARED = "COMPARED"
    AWAITING_EVAL = "AWAITING_EVAL"
    PROMOTED = "PROMOTED"
    REJECTED = "REJECTED"
    BLOCKED_NO_EVAL = "BLOCKED_NO_EVAL"
    NEEDS_HUMAN = "NEEDS_HUMAN"
    ROLLED_BACK = "ROLLED_BACK"


class InvalidAuthoringTransition(ValueError):
    pass


_A = AuthoringState

# 承認は WRITTEN の前提: AWAITING_APPROVAL から WRITTEN へは行けず、APPROVED → BASELINED を経る。
AUTHORING_TRANSITIONS: Mapping[AuthoringState, frozenset[AuthoringState]] = {
    _A.CLASSIFIED: frozenset({_A.EXPLORED, _A.NEEDS_HUMAN}),
    _A.EXPLORED: frozenset({_A.PLANNED, _A.NEEDS_HUMAN}),
    _A.PLANNED: frozenset({_A.AWAITING_APPROVAL, _A.BASELINED, _A.NEEDS_HUMAN}),
    _A.AWAITING_APPROVAL: frozenset({_A.APPROVED, _A.REJECTED, _A.NEEDS_HUMAN}),
    _A.APPROVED: frozenset({_A.BASELINED}),
    _A.BASELINED: frozenset({_A.WRITTEN, _A.BLOCKED_NO_EVAL}),
    _A.WRITTEN: frozenset({_A.VERIFYING, _A.ROLLED_BACK, _A.NEEDS_HUMAN}),
    _A.VERIFYING: frozenset(
        {
            _A.REPAIRING,
            _A.AWAITING_EVAL,
            _A.COMPARED,
            _A.BLOCKED_NO_EVAL,
            _A.NEEDS_HUMAN,
            _A.ROLLED_BACK,
        }
    ),
    _A.REPAIRING: frozenset({_A.VERIFYING, _A.NEEDS_HUMAN, _A.ROLLED_BACK}),
    _A.AWAITING_EVAL: frozenset({_A.COMPARED, _A.BLOCKED_NO_EVAL, _A.NEEDS_HUMAN}),
    _A.COMPARED: frozenset({_A.PROMOTED, _A.REJECTED, _A.NEEDS_HUMAN, _A.ROLLED_BACK}),
    _A.PROMOTED: frozenset({_A.ROLLED_BACK}),
    _A.REJECTED: frozenset(),
    _A.BLOCKED_NO_EVAL: frozenset(),
    _A.NEEDS_HUMAN: frozenset({_A.PLANNED}),
    _A.ROLLED_BACK: frozenset(),
}


@dataclass(frozen=True)
class AuthoringRecord:
    id: str
    target_kind: str
    target_paths: tuple[str, ...]
    risk: AuthoringRisk
    exploration: Mapping[str, object]
    spec: Mapping[str, object]
    plan_ref: str | None = None
    approval_ref: str | None = None
    baseline_run_id: str | None = None
    candidate_run_id: str | None = None
    state: AuthoringState = AuthoringState.CLASSIFIED

    def can_transition(self, nxt: AuthoringState) -> bool:
        """遷移表に加え、high_risk は承認なしに書込・昇格できないことを検査する。"""
        if nxt not in AUTHORING_TRANSITIONS[self.state]:
            return False
        if self.risk is not AuthoringRisk.HIGH_RISK:
            return True
        # high_risk は APPROVED を経由しないと BASELINED に入れない（PLANNED 直行禁止）。
        if self.state is AuthoringState.PLANNED and nxt is AuthoringState.BASELINED:
            return False
        if nxt in (AuthoringState.WRITTEN, AuthoringState.PROMOTED):
            return bool(self.approval_ref)
        return True


def transition_authoring(record: AuthoringRecord, nxt: AuthoringState) -> AuthoringRecord:
    if not record.can_transition(nxt):
        raise InvalidAuthoringTransition(f"{record.state.value} -> {nxt.value} is not allowed")
    return replace(record, state=nxt)
