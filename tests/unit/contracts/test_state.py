from dataclasses import replace

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
        S.RUNNING: {S.VERIFYING, S.WAITING_APPROVAL, S.FAILED, S.BLOCKED, S.CANCELLED},
        S.VERIFYING: {
            S.PASSED,
            S.REPAIRING,
            S.FAILED,
            S.WAITING_APPROVAL,
            S.BLOCKED,
            S.CANCELLED,
        },
        S.REPAIRING: {S.RUNNING, S.WAITING_APPROVAL, S.FAILED, S.BLOCKED, S.CANCELLED},
        S.WAITING_APPROVAL: {S.READY, S.VERIFYING, S.FAILED, S.BLOCKED, S.CANCELLED},
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
        A.WRITTEN: {A.VERIFYING, A.ROLLED_BACK, A.NEEDS_HUMAN},
        A.VERIFYING: {
            A.REPAIRING,
            A.AWAITING_EVAL,
            A.COMPARED,
            A.BLOCKED_NO_EVAL,
            A.NEEDS_HUMAN,
            A.ROLLED_BACK,
        },
        A.REPAIRING: {A.VERIFYING, A.NEEDS_HUMAN, A.ROLLED_BACK},
        A.AWAITING_EVAL: {A.COMPARED, A.BLOCKED_NO_EVAL, A.NEEDS_HUMAN},
        A.COMPARED: {A.PROMOTED, A.REJECTED, A.NEEDS_HUMAN, A.ROLLED_BACK},
        A.PROMOTED: {A.ROLLED_BACK},
        A.REJECTED: set(),
        A.BLOCKED_NO_EVAL: set(),
        A.NEEDS_HUMAN: {A.PLANNED},
        A.ROLLED_BACK: set(),
    }

    actual = {k: set(v) for k, v in AUTHORING_TRANSITIONS.items()}

    assert actual == expected


@pytest.mark.parametrize(
    ("current", "nxt"),
    [
        (S.RUNNING, S.WAITING_APPROVAL),
        (S.REPAIRING, S.WAITING_APPROVAL),
        (S.WAITING_APPROVAL, S.FAILED),
        (S.BLOCKED, S.FAILED),
        (S.BLOCKED, S.READY),
        (S.PENDING, S.BLOCKED),
    ],
)
def test_transition_added_pair_returns_next_state(current, nxt):
    result = transition(current, nxt)

    assert result is nxt


@pytest.mark.parametrize("state", list(UnitState))
def test_transition_self_transition_raises(state):
    with pytest.raises(InvalidTransition):
        transition(state, state)


@pytest.mark.parametrize("terminal", [S.PASSED, S.FAILED, S.CANCELLED])
@pytest.mark.parametrize("nxt", list(UnitState))
def test_transition_from_terminal_state_raises(terminal, nxt):
    with pytest.raises(InvalidTransition):
        transition(terminal, nxt)


def _record(risk, state, approval_ref=None):
    return AuthoringRecord(
        id="A1",
        target_kind="hook",
        target_paths=(".claude/settings.json",),
        risk=risk,
        exploration={},
        spec={},
        approval_ref=approval_ref,
        state=state,
    )


def test_transition_authoring_returns_record_with_next_state():
    record = _record(AuthoringRisk.BEHAVIORAL, A.APPROVED)

    result = transition_authoring(record, A.BASELINED)

    assert result == replace(record, state=A.BASELINED)


def test_transition_authoring_does_not_mutate_input_record():
    record = _record(AuthoringRisk.BEHAVIORAL, A.APPROVED)

    transition_authoring(record, A.BASELINED)

    assert record.state is A.APPROVED


def test_transition_authoring_awaiting_approval_to_written_raises():
    record = _record(AuthoringRisk.BEHAVIORAL, A.AWAITING_APPROVAL)

    with pytest.raises(InvalidAuthoringTransition):
        transition_authoring(record, A.WRITTEN)


def test_transition_authoring_high_risk_planned_to_baselined_raises_even_with_approval_ref():
    record = _record(AuthoringRisk.HIGH_RISK, A.PLANNED, approval_ref="approvals/1.json")

    with pytest.raises(InvalidAuthoringTransition):
        transition_authoring(record, A.BASELINED)


def test_transition_authoring_high_risk_baselined_to_written_without_approval_ref_raises():
    record = _record(AuthoringRisk.HIGH_RISK, A.BASELINED, approval_ref=None)

    with pytest.raises(InvalidAuthoringTransition):
        transition_authoring(record, A.WRITTEN)


def test_transition_authoring_high_risk_baselined_to_written_with_empty_approval_ref_raises():
    record = _record(AuthoringRisk.HIGH_RISK, A.BASELINED, approval_ref="")

    with pytest.raises(InvalidAuthoringTransition):
        transition_authoring(record, A.WRITTEN)


def test_transition_authoring_high_risk_compared_to_promoted_with_empty_approval_ref_raises():
    record = _record(AuthoringRisk.HIGH_RISK, A.COMPARED, approval_ref="")

    with pytest.raises(InvalidAuthoringTransition):
        transition_authoring(record, A.PROMOTED)


def test_transition_authoring_high_risk_baselined_to_written_with_approval_ref_succeeds():
    record = _record(AuthoringRisk.HIGH_RISK, A.BASELINED, approval_ref="approvals/1.json")

    result = transition_authoring(record, A.WRITTEN)

    assert result.state is A.WRITTEN


def test_transition_authoring_high_risk_regular_path_approved_to_baselined_succeeds():
    record = _record(AuthoringRisk.HIGH_RISK, A.AWAITING_APPROVAL)

    approved = transition_authoring(record, A.APPROVED)
    baselined = transition_authoring(approved, A.BASELINED)

    assert (approved.state, baselined.state) == (A.APPROVED, A.BASELINED)


def test_authoring_record_high_risk_compared_to_promoted_with_approval_ref_is_allowed():
    record = _record(AuthoringRisk.HIGH_RISK, A.COMPARED, approval_ref="approvals/1.json")

    allowed = record.can_transition(A.PROMOTED)

    assert allowed is True


def test_authoring_record_high_risk_planned_to_baselined_with_approval_ref_is_rejected():
    record = _record(AuthoringRisk.HIGH_RISK, A.PLANNED, approval_ref="approvals/1.json")

    allowed = record.can_transition(A.BASELINED)

    assert allowed is False


def test_authoring_record_high_risk_empty_approval_ref_is_not_approved():
    record = _record(AuthoringRisk.HIGH_RISK, A.BASELINED, approval_ref="")

    allowed = record.can_transition(A.WRITTEN)

    assert allowed is False


@pytest.mark.parametrize(
    ("current", "nxt"),
    [
        (A.CLASSIFIED, A.PROMOTED),
        (A.REJECTED, A.PLANNED),
        (A.PROMOTED, A.WRITTEN),
        (A.AWAITING_APPROVAL, A.WRITTEN),
    ],
)
def test_authoring_record_behavioral_off_table_transition_is_rejected(current, nxt):
    record = _record(AuthoringRisk.BEHAVIORAL, current)

    allowed = record.can_transition(nxt)

    assert allowed is False


@pytest.mark.parametrize(
    ("current", "nxt"),
    [
        (A.WRITTEN, A.ROLLED_BACK),
        (A.WRITTEN, A.NEEDS_HUMAN),
        (A.VERIFYING, A.ROLLED_BACK),
        (A.REPAIRING, A.ROLLED_BACK),
        (A.COMPARED, A.ROLLED_BACK),
    ],
)
def test_authoring_record_post_write_failure_transition_is_allowed(current, nxt):
    record = _record(AuthoringRisk.BEHAVIORAL, current)

    allowed = record.can_transition(nxt)

    assert allowed is True


def test_authoring_record_rejected_is_terminal():
    record = _record(AuthoringRisk.BEHAVIORAL, A.REJECTED)

    allowed = [record.can_transition(nxt) for nxt in AuthoringState]

    assert not any(allowed)


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
