import json
import os
import time

import pytest

from seh.contracts import RunContext, TerminalState
from seh.runtime.agent_runner import RunnerRegistry
from seh.runtime.runners.base import InvalidEventStream, Invocation
from seh.runtime.runners.opencode_cli import OpenCodeCliRunner, register


def test_argv_has_run_json_dir_and_no_prompt_or_pure(tmp_path):
    inv = OpenCodeCliRunner().build_invocation(
        "SECRET PROMPT", RunContext(tmp_path, tmp_path, 20, ("PATH",))
    )

    assert inv.argv == ("opencode", "run", "--format", "json", "--dir", str(tmp_path))
    assert "--pure" not in inv.argv
    assert inv.stdin == b"SECRET PROMPT"
    assert all("SECRET PROMPT" not in a for a in inv.argv)


def test_argv_adds_agent_and_auto_when_requested(tmp_path):
    inv = OpenCodeCliRunner(agent="build", auto_approve=True).build_invocation(
        "p", RunContext(tmp_path, tmp_path, 20, ("PATH",))
    )

    assert inv.argv[inv.argv.index("--agent") + 1] == "build"
    assert inv.argv[-1] == "--auto"


def test_auto_absent_by_default(tmp_path):
    inv = OpenCodeCliRunner().build_invocation("p", RunContext(tmp_path, tmp_path, 20, ("PATH",)))

    assert "--auto" not in inv.argv
    assert "--agent" not in inv.argv


def test_env_disables_claude_code_skills_discovery(tmp_path):
    inv = OpenCodeCliRunner().build_invocation("p", RunContext(tmp_path, tmp_path, 20, ("PATH",)))

    assert inv.env_extra["OPENCODE_DISABLE_CLAUDE_CODE_SKILLS"] == "1"


def test_parse_events_skips_blank_lines():
    out = b'{"type":"a"}\n\n  \n{"type":"b"}\n'

    assert OpenCodeCliRunner().parse_events(out) == [{"type": "a"}, {"type": "b"}]


def test_parse_events_empty_stdout_is_empty_list():
    assert OpenCodeCliRunner().parse_events(b"") == []


def test_parse_events_rejects_invalid_json_line():
    with pytest.raises(InvalidEventStream):
        OpenCodeCliRunner().parse_events(b'{"type":"a"}\nnot json\n')


def test_parse_events_rejects_non_object_line():
    with pytest.raises(InvalidEventStream):
        OpenCodeCliRunner().parse_events(b"[1]\n")


def test_success_concatenates_text_and_sums_usage():
    events = [
        {"type": "text", "part": {"text": "Hello "}},
        {
            "type": "step_finish",
            "part": {"reason": "tool-calls", "tokens": {"input": 10, "output": 2}, "cost": 0.25},
        },
        {"type": "text", "part": {"text": "world"}},
        {
            "type": "step_finish",
            "part": {"reason": "stop", "tokens": {"input": 5, "output": 3}, "cost": 0.5},
        },
    ]
    runner = OpenCodeCliRunner()

    decision = runner.detect_terminal(events, 0, b"")
    usage = runner.normalize_usage(events)

    assert decision.state is TerminalState.SUCCESS
    assert decision.final_response == "Hello world"
    assert usage is not None
    assert (usage.input_tokens, usage.output_tokens, usage.cost_usd) == (15, 5, 0.75)
    assert usage.raw is not None
    assert usage.raw["schema"] == "UNVERIFIED"


def test_success_without_text_has_no_final_response():
    events = [{"type": "step_finish", "part": {"reason": "stop"}}]

    decision = OpenCodeCliRunner().detect_terminal(events, 0, b"")

    assert decision.state is TerminalState.SUCCESS
    assert decision.final_response is None


def test_reason_at_top_level_is_accepted():
    events = [{"type": "step_finish", "reason": "stop"}]

    decision = OpenCodeCliRunner().detect_terminal(events, 0, b"")

    assert decision.state is TerminalState.SUCCESS


def test_usage_item_is_none_when_any_step_lacks_it():
    events = [
        {
            "type": "step_finish",
            "part": {"reason": "tool-calls", "tokens": {"input": 1, "output": 1}, "cost": 0.1},
        },
        {"type": "step_finish", "part": {"reason": "stop", "tokens": {"input": 2}}},
    ]

    usage = OpenCodeCliRunner().normalize_usage(events)

    assert usage is not None
    assert (usage.input_tokens, usage.output_tokens, usage.cost_usd) == (3, None, None)


def test_usage_is_none_without_step_finish():
    assert OpenCodeCliRunner().normalize_usage([{"type": "text", "part": {"text": "x"}}]) is None


def test_empty_events_is_invalid_output_empty_output():
    decision = OpenCodeCliRunner().detect_terminal([], 0, b"")

    assert decision.state is TerminalState.INVALID_OUTPUT
    assert decision.error_code == "EMPTY_OUTPUT"


def test_error_event_is_failed():
    events = [
        {"type": "error", "error": {"name": "X"}},
        {"type": "step_finish", "part": {"reason": "stop"}},
    ]

    decision = OpenCodeCliRunner().detect_terminal(events, 0, b"")

    assert decision.state is TerminalState.FAILED
    assert decision.error_code == "OPENCODE_ERROR"


def test_tool_use_with_error_status_is_failed():
    events = [
        {"type": "tool_use", "part": {"state": {"status": "error"}}},
        {"type": "step_finish", "part": {"reason": "stop"}},
    ]

    decision = OpenCodeCliRunner().detect_terminal(events, 0, b"")

    assert decision.state is TerminalState.FAILED
    assert decision.error_code == "TOOL_ERROR"


def test_tool_use_with_top_level_state_error_is_failed():
    events = [
        {"type": "tool_use", "state": {"status": "error"}},
        {"type": "step_finish", "part": {"reason": "stop"}},
    ]

    decision = OpenCodeCliRunner().detect_terminal(events, 0, b"")

    assert decision.error_code == "TOOL_ERROR"


def test_tool_use_completed_does_not_fail():
    events = [
        {"type": "tool_use", "part": {"state": {"status": "completed"}}},
        {"type": "step_finish", "part": {"reason": "stop"}},
    ]

    decision = OpenCodeCliRunner().detect_terminal(events, 0, b"")

    assert decision.state is TerminalState.SUCCESS


def test_ending_with_tool_calls_is_no_terminal_event():
    events = [{"type": "step_finish", "part": {"reason": "tool-calls"}}]

    decision = OpenCodeCliRunner().detect_terminal(events, 0, b"")

    assert decision.state is TerminalState.INVALID_OUTPUT
    assert decision.error_code == "NO_TERMINAL_EVENT"


def test_missing_step_finish_is_no_terminal_event():
    events = [{"type": "text", "part": {"text": "partial"}}]

    decision = OpenCodeCliRunner().detect_terminal(events, 0, b"")

    assert decision.state is TerminalState.INVALID_OUTPUT
    assert decision.error_code == "NO_TERMINAL_EVENT"


@pytest.mark.parametrize("stderr", [b"auth failed", b"Please login", b"bad API key", b"HTTP 401"])
def test_auth_hint_in_stderr_with_nonzero_exit_is_blocked_auth(stderr):
    events = [{"type": "text", "part": {"text": "x"}}]

    decision = OpenCodeCliRunner().detect_terminal(events, 1, stderr)

    assert decision.state is TerminalState.BLOCKED_AUTH
    assert decision.error_code == "AUTH_SUSPECTED"


def test_auth_hint_with_empty_events_and_nonzero_exit_is_blocked_auth():
    decision = OpenCodeCliRunner().detect_terminal([], 1, b"401 Unauthorized")

    assert decision.state is TerminalState.BLOCKED_AUTH


def test_probe_spec_requires_run_flags():
    spec = OpenCodeCliRunner().probe_spec()

    assert spec.command == "opencode"
    assert spec.help_args == ("run", "--help")
    assert spec.required_flags == {
        "format": ("--format",),
        "dir": ("--dir",),
        "agent": ("--agent",),
    }


def test_register_adds_opencode_runner():
    registry = RunnerRegistry()

    register(registry)

    assert registry.get("opencode").host == "opencode"


async def test_run_once_success_with_real_process(tmp_path):
    lines = [
        {"type": "text", "part": {"text": "ok"}},
        {
            "type": "step_finish",
            "part": {"reason": "stop", "tokens": {"input": 1, "output": 2}, "cost": 0.1},
        },
    ]
    payload = json.dumps(lines)
    script = f"import json;[print(json.dumps(e)) for e in json.loads({payload!r})]"

    class Scripted(OpenCodeCliRunner):
        def build_invocation(self, prompt, context):
            return Invocation(("python3", "-c", script), prompt.encode())

    result = await Scripted().run_once("hi", RunContext(tmp_path, tmp_path, 20, ("PATH",)))

    assert result.terminal_state is TerminalState.SUCCESS
    assert result.final_response == "ok"
    assert result.usage is not None
    assert result.usage.input_tokens == 1


async def test_run_once_exit_zero_with_empty_output_is_invalid_output(tmp_path):
    class Silent(OpenCodeCliRunner):
        def build_invocation(self, prompt, context):
            return Invocation(("python3", "-c", "pass"), None)

    result = await Silent().run_once("hi", RunContext(tmp_path, tmp_path, 20, ("PATH",)))

    assert result.exit_code == 0
    assert result.terminal_state is TerminalState.INVALID_OUTPUT
    assert result.error_code == "EMPTY_OUTPUT"


async def test_run_once_hang_times_out_and_leaves_no_process(tmp_path):
    pid_file = tmp_path / "pid"
    script = f"import os,time;open({str(pid_file)!r},'w').write(str(os.getpid()));time.sleep(60)"

    class Hanging(OpenCodeCliRunner):
        def build_invocation(self, prompt, context):
            return Invocation(("python3", "-c", script), None)

    result = await Hanging().run_once("hi", RunContext(tmp_path, tmp_path, 1, ("PATH",)))

    assert result.terminal_state is TerminalState.TIMED_OUT
    pid = int(pid_file.read_text())
    deadline = time.monotonic() + 3
    alive = True
    while alive and time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
            time.sleep(0.05)
        except ProcessLookupError:
            alive = False
    assert not alive
