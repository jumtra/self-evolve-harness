import pytest

from seh.contracts import (
    ALLOWED_TRANSITIONS,
    AUTHORING_TRANSITIONS,
    AuthoringRecord,
    AuthoringRisk,
    AuthoringState,
    InvalidAuthoringTransition,
    InvalidTransition,
    UnitState,
    transition,
    transition_authoring,
)

S = UnitState
A = AuthoringState


def test_allowed_transitions_table_matches_expected_exactly():
    expected = {
        S.PENDING: {S.READY, S.BLOCKED, S.CANCELLED},
        S.READY: {S.RUNNING, S.WAITING_APPROVAL, S.BLOCKED, S.CANCELLED},
        S.RUNNING: {S.VERIFYING, S.FAILED, S.BLOCKED, S.CANCELLED},
        S.VERIFYING: {
            S.PASSED,
            S.REPAIRING,
            S.FAILED,
            S.WAITING_APPROVAL,
            S.BLOCKED,
            S.CANCELLED,
        },
        S.REPAIRING: {S.RUNNING, S.FAILED, S.BLOCKED, S.CANCELLED},
        S.WAITING_APPROVAL: {S.READY, S.VERIFYING, S.BLOCKED, S.CANCELLED},
        S.BLOCKED: {S.READY, S.FAILED, S.CANCELLED},
        S.PASSED: set(),
        S.FAILED: set(),
        S.CANCELLED: set(),
    }

    actual = {k: set(v) for k, v in ALLOWED_TRANSITIONS.items()}

    assert actual == expected


@pytest.mark.parametrize(
    ("current", "nxt"),
    [
        (S.PENDING, S.READY),
        (S.READY, S.RUNNING),
        (S.RUNNING, S.VERIFYING),
        (S.VERIFYING, S.PASSED),
        (S.VERIFYING, S.REPAIRING),
        (S.REPAIRING, S.RUNNING),
        (S.VERIFYING, S.WAITING_APPROVAL),
        (S.WAITING_APPROVAL, S.VERIFYING),
        (S.RUNNING, S.FAILED),
    ],
)
def test_transition_allowed_pair_returns_next_state(current, nxt):
    result = transition(current, nxt)

    assert result is nxt


@pytest.mark.parametrize(
    ("current", "nxt"),
    [
        pytest.param(S.RUNNING, S.PASSED, id="running_to_passed_skips_verification"),
        pytest.param(S.PASSED, S.RUNNING, id="terminal_passed_cannot_restart"),
        pytest.param(S.PENDING, S.PASSED, id="pending_to_passed"),
        pytest.param(S.WAITING_APPROVAL, S.PASSED, id="approval_resume_skips_verification"),
    ],
)
def test_transition_forbidden_pair_raises_invalid_transition(current, nxt):
    with pytest.raises(InvalidTransition):
        transition(current, nxt)


def test_authoring_transitions_table_matches_expected_exactly():
    expected = {
        A.CLASSIFIED: {A.EXPLORED, A.NEEDS_HUMAN},
        A.EXPLORED: {A.PLANNED, A.NEEDS_HUMAN},
        A.PLANNED: {A.AWAITING_APPROVAL, A.BASELINED, A.NEEDS_HUMAN},
        A.AWAITING_APPROVAL: {A.APPROVED, A.REJECTED, A.NEEDS_HUMAN},
        A.APPROVED: {A.BASELINED},
        A.BASELINED: {A.WRITTEN, A.BLOCKED_NO_EVAL},
        A.WRITTEN: {A.VERIFYING},
        A.VERIFYING: {A.REPAIRING, A.AWAITING_EVAL, A.COMPARED, A.BLOCKED_NO_EVAL, A.NEEDS_HUMAN},
        A.REPAIRING: {A.VERIFYING, A.NEEDS_HUMAN},
        A.AWAITING_EVAL: {A.COMPARED, A.BLOCKED_NO_EVAL, A.NEEDS_HUMAN},
        A.COMPARED: {A.PROMOTED, A.REJECTED, A.NEEDS_HUMAN},
        A.PROMOTED: {A.ROLLED_BACK},
        A.REJECTED: set(),
        A.BLOCKED_NO_EVAL: set(),
        A.NEEDS_HUMAN: {A.PLANNED},
        A.ROLLED_BACK: set(),
    }

    actual = {k: set(v) for k, v in AUTHORING_TRANSITIONS.items()}

    assert actual == expected


def test_transition_authoring_awaiting_approval_to_written_raises():
    with pytest.raises(InvalidAuthoringTransition):
        transition_authoring(A.AWAITING_APPROVAL, A.WRITTEN)


def test_transition_authoring_allowed_pair_returns_next_state():
    result = transition_authoring(A.APPROVED, A.BASELINED)

    assert result is A.BASELINED


def test_authoring_record_high_risk_planned_to_baselined_without_approval_is_rejected():
    record = AuthoringRecord(
        id="A1",
        target_kind="hook",
        target_paths=(".claude/settings.json",),
        risk=AuthoringRisk.HIGH_RISK,
        exploration={},
        spec={},
        state=A.PLANNED,
    )

    allowed = record.can_transition(A.BASELINED)

    assert allowed is False


def test_authoring_record_high_risk_baselined_to_written_without_approval_ref_is_rejected():
    record = AuthoringRecord(
        id="A1",
        target_kind="hook",
        target_paths=(".claude/settings.json",),
        risk=AuthoringRisk.HIGH_RISK,
        exploration={},
        spec={},
        approval_ref=None,
        state=A.BASELINED,
    )

    allowed = record.can_transition(A.WRITTEN)

    assert allowed is False


def test_authoring_record_high_risk_baselined_to_written_with_approval_ref_is_allowed():
    record = AuthoringRecord(
        id="A1",
        target_kind="hook",
        target_paths=(".claude/settings.json",),
        risk=AuthoringRisk.HIGH_RISK,
        exploration={},
        spec={},
        approval_ref="approvals/1.json",
        state=A.BASELINED,
    )

    allowed = record.can_transition(A.WRITTEN)

    assert allowed is True


def test_authoring_record_high_risk_compared_to_promoted_without_approval_ref_is_rejected():
    record = AuthoringRecord(
        id="A1",
        target_kind="hook",
        target_paths=(".claude/settings.json",),
        risk=AuthoringRisk.HIGH_RISK,
        exploration={},
        spec={},
        approval_ref=None,
        state=A.COMPARED,
    )

    allowed = record.can_transition(A.PROMOTED)

    assert allowed is False


def test_authoring_record_behavioral_planned_to_baselined_is_allowed_without_approval():
    record = AuthoringRecord(
        id="A2",
        target_kind="skill",
        target_paths=("skills/x/SKILL.md",),
        risk=AuthoringRisk.BEHAVIORAL,
        exploration={},
        spec={},
        state=A.PLANNED,
    )

    allowed = record.can_transition(A.BASELINED)

    assert allowed is True
