import json
from pathlib import Path

import pytest

from seh import events
from seh.contracts import HostId
from seh.events import HookDecision, HookInput, evaluate, run_hook
from seh.policy import Policy

_RM = "r" + "m -" + "rf "
_SUDO = "su" + "do"


@pytest.mark.parametrize("tool", ["apply_patch", "local_shell", "run_terminal_command"])
def test_command_is_evaluated_regardless_of_tool_name(tool: str, tmp_path: Path) -> None:
    outcome = evaluate(
        HookInput("PreToolUse", HostId.CLAUDE, tool, "git push origin main", (), tmp_path, {}),
        policy=Policy(),
    )

    assert outcome.decision == HookDecision.ASK


def test_catastrophic_command_is_denied_for_unknown_tool(tmp_path: Path) -> None:
    outcome = evaluate(
        HookInput("PreToolUse", HostId.CLAUDE, "local_shell", _RM + "/", (), tmp_path, {}),
        policy=Policy(),
    )

    assert outcome.reason_code == "CATASTROPHIC_COMMAND"


@pytest.mark.parametrize(
    "command",
    [
        _RM + "//",
        _RM + "/.",
        _RM + "~/",
        _SUDO + " -u root " + _RM + "/",
        "FOO=1 env -i " + _RM + "/",
    ],
)
def test_catastrophic_variants_are_denied(command: str, tmp_path: Path) -> None:
    outcome = evaluate(
        HookInput("PreToolUse", HostId.CLAUDE, "Bash", command, (), tmp_path, {}), policy=Policy()
    )

    assert outcome.decision == HookDecision.DENY
    assert outcome.reason_code == "CATASTROPHIC_COMMAND"


def test_unparseable_command_is_denied(tmp_path: Path) -> None:
    outcome = evaluate(
        HookInput("PreToolUse", HostId.CLAUDE, "Bash", 'echo "unterminated', (), tmp_path, {}),
        policy=Policy(),
    )

    assert outcome.decision == HookDecision.DENY
    assert outcome.reason_code == "UNPARSEABLE_COMMAND"


def test_events_module_no_longer_duplicates_policy_tokenizer() -> None:
    duplicated = {
        "_WRAPPERS",
        "_SEGMENT_SPLIT",
        "_segments",
        "_SENSITIVE_NAME_GLOBS",
        "_TOOL_CONFIG_GLOBS",
        "_relative_to_cwd",
    }

    assert not duplicated & set(vars(events))


@pytest.mark.parametrize(
    ("tool_input", "reason"),
    [
        ({"notebook_path": ".env"}, "SENSITIVE_FILE"),
        ({"edit": {"target_path": "ruff.toml"}}, "PROTECTED_TOOL_CONFIG"),
        ({"paths": [".claude/settings.json"]}, "PROTECTED_PATH"),
    ],
)
def test_path_like_keys_are_judged(tool_input: dict[str, object], reason: str) -> None:
    payload = json.dumps({"tool_name": "NotebookEdit", "tool_input": tool_input, "cwd": "/w"})
    inp = events.parse_hook_input("PreToolUse", HostId.CLAUDE, payload.encode())

    outcome = evaluate(inp, policy=Policy())

    assert outcome.reason_code == reason


def test_absolute_path_outside_cwd_asks(tmp_path: Path) -> None:
    inp = HookInput("PreToolUse", HostId.CLAUDE, "Write", None, ("/etc/hosts",), tmp_path, {})

    outcome = evaluate(inp, policy=Policy())

    assert outcome.decision == HookDecision.ASK
    assert outcome.reason_code == "PROTECTED_PATH"


def test_external_effect_reason_and_message_come_from_policy(tmp_path: Path) -> None:
    outcome = evaluate(
        HookInput("PreToolUse", HostId.CLAUDE, "Bash", "git push origin main", (), tmp_path, {}),
        policy=Policy(),
    )

    assert outcome.reason_code == "EXTERNAL_EFFECT_REQUIRES_APPROVAL"
    assert outcome.message == "human confirmation required"


def test_r2_reason_and_message_come_from_policy(tmp_path: Path) -> None:
    outcome = evaluate(
        HookInput("PreToolUse", HostId.CLAUDE, "Bash", "rm -rf build", (), tmp_path, {}),
        policy=Policy(),
    )

    assert outcome.reason_code == "R2_REQUIRES_APPROVAL"
    assert outcome.message == "human confirmation required"


def test_unattended_run_turns_ask_into_deny(tmp_path: Path) -> None:
    payload = json.dumps(
        {"tool_name": "Bash", "tool_input": {"command": "rm -rf build"}, "cwd": str(tmp_path)}
    ).encode()

    code, _, stderr = run_hook(
        "PreToolUse", HostId.CLAUDE, payload, policy=Policy(), trace=None, unattended=True
    )

    assert code == 2
    assert "無人実行では承認できない" in stderr


def test_attended_run_keeps_ask(tmp_path: Path) -> None:
    payload = json.dumps(
        {"tool_name": "Bash", "tool_input": {"command": "rm -rf build"}, "cwd": str(tmp_path)}
    ).encode()

    code, stdout, _ = run_hook(
        "PreToolUse", HostId.CLAUDE, payload, policy=Policy(), trace=None, unattended=False
    )

    assert code == 0
    assert json.loads(stdout)["hookSpecificOutput"]["permissionDecision"] == "ask"
