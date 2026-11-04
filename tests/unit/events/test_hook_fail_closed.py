import json
from datetime import datetime
from pathlib import Path

import pytest

from seh import events
from seh.contracts import HostId
from seh.events import SESSION_START_HANDLERS, HookInput, run_hook
from seh.policy import Action, ApprovalToken, Decision, Policy
from seh.trace import TraceWriter, read_trace


class ExplodingPolicy(Policy):
    def authorize(
        self,
        action: Action,
        *,
        unattended: bool,
        token: ApprovalToken | None = None,
        token_scope: str | None = None,
        target_digest: str | None = None,
        now: datetime,
    ) -> Decision:
        raise RuntimeError("boom")


def test_unknown_event_is_blocked_for_claude() -> None:
    code, _, stderr = run_hook("Bogus", HostId.CLAUDE, b"{}", policy=Policy(), trace=None)

    assert code == 2
    assert stderr != ""


def test_malformed_pretooluse_is_blocked_for_claude() -> None:
    code, _, stderr = run_hook("PreToolUse", HostId.CLAUDE, b"{oops", policy=Policy(), trace=None)

    assert code == 2
    assert stderr != ""


def test_malformed_pretooluse_on_antigravity_returns_deny_json() -> None:
    code, stdout, _ = run_hook(
        "PreToolUse", HostId.ANTIGRAVITY, b"{oops", policy=Policy(), trace=None
    )

    assert code == 0
    assert json.loads(stdout)["decision"] == "deny"


def test_policy_exception_blocks_pretooluse() -> None:
    payload = json.dumps(
        {"tool_name": "Bash", "tool_input": {"command": "ls"}, "cwd": "/"}
    ).encode()

    code, _, stderr = run_hook(
        "PreToolUse", HostId.CLAUDE, payload, policy=ExplodingPolicy(), trace=None
    )

    assert code == 2
    assert "RuntimeError" in stderr


def test_policy_exception_on_antigravity_returns_deny_json() -> None:
    payload = json.dumps(
        {"toolCall": {"name": "run_command", "args": {"command": "ls"}}, "workspacePaths": ["/"]}
    ).encode()

    code, stdout, _ = run_hook(
        "PreToolUse", HostId.ANTIGRAVITY, payload, policy=ExplodingPolicy(), trace=None
    )

    assert code == 0
    assert json.loads(stdout)["decision"] == "deny"


def test_session_start_exception_warns_and_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    def failing_handler(inp: HookInput) -> str | None:
        raise RuntimeError("handler broke")

    monkeypatch.setattr(events, "SESSION_START_HANDLERS", [failing_handler])

    code, stdout, stderr = run_hook(
        "SessionStart", HostId.CLAUDE, b"{}", policy=Policy(), trace=None
    )

    assert code == 0
    assert stdout == ""
    assert "警告" in stderr


def test_malformed_session_start_warns_and_passes() -> None:
    code, _, stderr = run_hook("SessionStart", HostId.CLAUDE, b"nope", policy=Policy(), trace=None)

    assert code == 0
    assert "警告" in stderr


def test_session_start_handler_outputs_are_joined_on_stdout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        events, "SESSION_START_HANDLERS", [lambda inp: "one", lambda inp: None, lambda inp: "two"]
    )

    code, stdout, _ = run_hook("SessionStart", HostId.CLAUDE, b"{}", policy=Policy(), trace=None)

    assert code == 0
    assert stdout == "one\ntwo"


def test_session_start_handlers_are_empty_by_default() -> None:
    assert SESSION_START_HANDLERS == []


def test_trace_records_decision_with_command_hash_only(tmp_path: Path) -> None:
    trace_path = tmp_path / "hook-trace.jsonl"
    command = "rm -rf build"
    payload = json.dumps(
        {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": str(tmp_path)}
    ).encode()

    run_hook("PreToolUse", HostId.CLAUDE, payload, policy=Policy(), trace=TraceWriter(trace_path))

    raw_text = trace_path.read_text(encoding="utf-8")
    record = read_trace(trace_path)[0]
    assert record["data"]["decision"] == "ask"
    assert record["data"]["reason_code"] == "R2_REQUIRES_APPROVAL"
    assert len(record["data"]["command_sha256"]) == 64
    assert command not in raw_text
