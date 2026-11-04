import json

import pytest

from seh.contracts import HostId
from seh.events import HookDecision, HookOutcome, render_outcome


def test_claude_deny_exits_2_with_message_on_stderr() -> None:
    outcome = HookOutcome(HookDecision.DENY, "SENSITIVE_FILE", "blocked")

    assert render_outcome(outcome, HostId.CLAUDE) == (2, "", "blocked")


def test_claude_ask_returns_permission_decision_json() -> None:
    outcome = HookOutcome(HookDecision.ASK, "R2_REQUIRES_APPROVAL", "need approval")

    code, stdout, stderr = render_outcome(outcome, HostId.CLAUDE)

    assert code == 0
    assert stderr == ""
    assert json.loads(stdout) == {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "ask",
            "permissionDecisionReason": "need approval",
        }
    }


def test_claude_allow_is_silent() -> None:
    outcome = HookOutcome(HookDecision.ALLOW, "ALLOWED", "")

    assert render_outcome(outcome, HostId.CLAUDE) == (0, "", "")


def test_codex_deny_exits_2() -> None:
    outcome = HookOutcome(HookDecision.DENY, "SENSITIVE_FILE", "blocked")

    assert render_outcome(outcome, HostId.CODEX) == (2, "", "blocked")


def test_codex_ask_is_conservatively_blocked_with_approval_note() -> None:
    outcome = HookOutcome(HookDecision.ASK, "R2_REQUIRES_APPROVAL", "danger")

    code, stdout, stderr = render_outcome(outcome, HostId.CODEX)

    assert code == 2
    assert stdout == ""
    assert "承認が必要" in stderr
    assert "danger" in stderr


def test_codex_allow_is_silent() -> None:
    outcome = HookOutcome(HookDecision.ALLOW, "ALLOWED", "")

    assert render_outcome(outcome, HostId.CODEX) == (0, "", "")


def test_antigravity_deny_prints_deny_json_with_exit_0() -> None:
    outcome = HookOutcome(HookDecision.DENY, "SENSITIVE_FILE", "blocked")

    code, stdout, stderr = render_outcome(outcome, HostId.ANTIGRAVITY)

    assert code == 0
    assert stderr == ""
    assert json.loads(stdout) == {"decision": "deny", "reason": "blocked"}


def test_antigravity_ask_is_rendered_as_deny_json() -> None:
    outcome = HookOutcome(HookDecision.ASK, "PROTECTED_PATH", "confirm")

    code, stdout, _ = render_outcome(outcome, HostId.ANTIGRAVITY)

    assert code == 0
    assert json.loads(stdout) == {"decision": "deny", "reason": "confirm"}


def test_antigravity_allow_is_silent() -> None:
    outcome = HookOutcome(HookDecision.ALLOW, "ALLOWED", "")

    assert render_outcome(outcome, HostId.ANTIGRAVITY) == (0, "", "")


@pytest.mark.parametrize("decision", [HookDecision.DENY, HookDecision.ASK])
def test_opencode_deny_and_ask_exit_2(decision: HookDecision) -> None:
    outcome = HookOutcome(decision, "X", "stop it")

    assert render_outcome(outcome, HostId.OPENCODE) == (2, "", "stop it")


def test_opencode_allow_is_silent() -> None:
    outcome = HookOutcome(HookDecision.ALLOW, "ALLOWED", "")

    assert render_outcome(outcome, HostId.OPENCODE) == (0, "", "")
