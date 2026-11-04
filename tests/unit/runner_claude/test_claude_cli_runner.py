import asyncio
import json

import pytest

from seh.contracts import RunContext, TerminalState
from seh.runtime.agent_runner import RunnerRegistry
from seh.runtime.process import DEFAULT_ENV_ALLOWLIST
from seh.runtime.runners.base import InvalidEventStream, Invocation
from seh.runtime.runners.claude_cli import ClaudeCliRunner, register


def test_build_invocation_minimal_argv_and_prompt_on_stdin(tmp_path):
    runner = ClaudeCliRunner()

    inv = runner.build_invocation(
        "hello prompt",
        RunContext(
            worktree=tmp_path,
            cwd=tmp_path,
            deadline_seconds=30,
            env_allowlist=DEFAULT_ENV_ALLOWLIST,
        ),
    )

    assert inv.argv == (
        "claude",
        "-p",
        "--output-format",
        "stream-json",
        "--verbose",
        "--permission-prompts",
        "none",
    )
    assert inv.stdin == b"hello prompt"
    assert "hello prompt" not in inv.argv
    assert "--bare" not in inv.argv
    assert dict(inv.env_extra) == {}


def test_build_invocation_appends_all_options(tmp_path):
    schema = {"type": "object"}
    runner = ClaudeCliRunner(
        json_schema=schema,
        allowed_tools=["Read", "Grep"],
        permission_mode="plan",
        max_budget_usd=1.5,
    )

    inv = runner.build_invocation(
        "p",
        RunContext(
            worktree=tmp_path,
            cwd=tmp_path,
            deadline_seconds=30,
            env_allowlist=DEFAULT_ENV_ALLOWLIST,
        ),
    )

    assert inv.argv[7:] == (
        "--json-schema",
        json.dumps(schema),
        "--allowedTools",
        "Read",
        "Grep",
        "--permission-mode",
        "plan",
        "--max-budget-usd",
        "1.5",
    )


def test_detect_terminal_success():
    runner = ClaudeCliRunner()
    stdout = (
        '{"type":"system","subtype":"init"}\n'
        "\n"
        '{"type":"result","subtype":"success","is_error":false,"result":"done",'
        '"permission_denials":[]}\n'
    )

    events = runner.parse_events(stdout.encode())
    decision = runner.detect_terminal(events, 0, b"")

    assert decision.state is TerminalState.SUCCESS
    assert decision.error_code is None
    assert decision.final_response == "done"
    assert decision.permission_denials == ()


@pytest.mark.parametrize(
    "subtype",
    [
        "error_max_turns",
        "error_max_budget_usd",
        "error_during_execution",
        "error_max_structured_output_retries",
    ],
)
def test_detect_terminal_error_subtypes_are_failed_with_uppercase_code(subtype):
    runner = ClaudeCliRunner()
    stdout = json.dumps({"type": "result", "subtype": subtype, "is_error": True}) + "\n"

    events = runner.parse_events(stdout.encode())
    decision = runner.detect_terminal(events, 1, b"")

    assert decision.state is TerminalState.FAILED
    assert decision.error_code == subtype.upper()


def test_detect_terminal_is_error_true_with_success_subtype_is_failed():
    runner = ClaudeCliRunner()
    stdout = '{"type":"result","subtype":"success","is_error":true,"result":"boom"}\n'

    events = runner.parse_events(stdout.encode())
    decision = runner.detect_terminal(events, 1, b"")

    assert decision.state is TerminalState.FAILED


def test_detect_terminal_without_result_event_is_invalid_output():
    runner = ClaudeCliRunner()
    stdout = '{"type":"system","subtype":"init"}\n{"type":"assistant"}\n'

    events = runner.parse_events(stdout.encode())
    decision = runner.detect_terminal(events, 0, b"")

    assert decision.state is TerminalState.INVALID_OUTPUT
    assert decision.error_code == "NO_TERMINAL_EVENT"


def test_parse_events_rejects_malformed_json_line():
    runner = ClaudeCliRunner()

    with pytest.raises(InvalidEventStream):
        runner.parse_events(b'{"type":"system"}\nnot json\n')


def test_detect_terminal_api_retry_authentication_is_blocked_auth():
    runner = ClaudeCliRunner()
    stdout = (
        '{"type":"system","subtype":"api_retry","error":"authentication_failed"}\n'
        '{"type":"result","subtype":"error_during_execution","is_error":true}\n'
    )

    events = runner.parse_events(stdout.encode())
    decision = runner.detect_terminal(events, 1, b"")

    assert decision.state is TerminalState.BLOCKED_AUTH


@pytest.mark.parametrize("text", ["Invalid API key", "Not logged in", "authentication error"])
def test_detect_terminal_result_text_auth_is_blocked_auth(text):
    runner = ClaudeCliRunner()
    stdout = json.dumps({"type": "result", "subtype": "success", "is_error": True, "result": text})

    events = runner.parse_events(stdout.encode())
    decision = runner.detect_terminal(events, 1, b"")

    assert decision.state is TerminalState.BLOCKED_AUTH


def test_detect_terminal_extracts_permission_denials():
    runner = ClaudeCliRunner()
    stdout = (
        '{"type":"result","subtype":"success","is_error":false,"result":"x",'
        '"permission_denials":[{"tool_name":"Bash","tool_use_id":"t1",'
        '"tool_input":{"command":"ls"}}]}\n'
    )

    events = runner.parse_events(stdout.encode())
    decision = runner.detect_terminal(events, 0, b"")

    assert decision.permission_denials == (
        {"tool_name": "Bash", "tool_use_id": "t1", "tool_input": {"command": "ls"}},
    )


def test_detect_terminal_missing_structured_output_with_schema_is_invalid_output():
    runner = ClaudeCliRunner(json_schema={"type": "object"})
    stdout = '{"type":"result","subtype":"success","is_error":false,"result":"x"}\n'

    events = runner.parse_events(stdout.encode())
    decision = runner.detect_terminal(events, 0, b"")

    assert decision.state is TerminalState.INVALID_OUTPUT
    assert decision.error_code == "STRUCTURED_OUTPUT_MISSING"


def test_detect_terminal_returns_structured_output_when_present():
    runner = ClaudeCliRunner(json_schema={"type": "object"})
    stdout = (
        '{"type":"result","subtype":"success","is_error":false,"result":"x",'
        '"structured_output":{"a":1}}\n'
    )

    events = runner.parse_events(stdout.encode())
    decision = runner.detect_terminal(events, 0, b"")

    assert decision.state is TerminalState.SUCCESS
    assert decision.structured_output == {"a": 1}


def test_normalize_usage_sums_model_usage_and_marks_cost_estimate():
    runner = ClaudeCliRunner()
    events = runner.parse_events(
        b'{"type":"result","subtype":"success","is_error":false,'
        b'"usage":{"input_tokens":1,"output_tokens":1},'
        b'"total_cost_usd":0.25,'
        b'"modelUsage":{"m1":{"inputTokens":10,"outputTokens":5},'
        b'"m2":{"inputTokens":20,"outputTokens":7}}}\n'
    )

    usage = runner.normalize_usage(events)

    assert usage is not None
    assert usage.input_tokens == 30
    assert usage.output_tokens == 12
    assert usage.cost_usd == 0.25
    assert usage.raw is not None
    assert usage.raw["cost_is_estimate"] is True


def test_normalize_usage_falls_back_to_usage_field():
    runner = ClaudeCliRunner()
    events = runner.parse_events(
        b'{"type":"result","subtype":"success","is_error":false,'
        b'"usage":{"input_tokens":3,"output_tokens":4}}\n'
    )

    usage = runner.normalize_usage(events)

    assert usage is not None
    assert (usage.input_tokens, usage.output_tokens) == (3, 4)
    assert usage.cost_usd is None


def test_normalize_usage_none_when_no_usage_info():
    runner = ClaudeCliRunner()
    events = runner.parse_events(b'{"type":"result","subtype":"success","is_error":false}\n')

    assert runner.normalize_usage(events) is None


def test_probe_spec_requires_documented_flags():
    spec = ClaudeCliRunner().probe_spec()

    assert spec.command == "claude"
    assert dict(spec.required_flags) == {
        "print": ("-p",),
        "output_format": ("--output-format",),
        "json_schema": ("--json-schema",),
        "allowed_tools": ("--allowedTools",),
        "permission_prompts": ("--permission-prompts",),
    }


def test_register_adds_runner_under_claude_host():
    registry = RunnerRegistry()

    register(registry)

    assert registry.get("claude").host == "claude"


def test_run_once_success_with_real_process(tmp_path):
    script = (
        "import sys;sys.stdin.read();"
        'print(\'{"type":"result","subtype":"success","is_error":false,"result":"ok"}\')'
    )

    class ScriptedClaude(ClaudeCliRunner):
        command = "python3"

        def build_invocation(self, prompt, context):
            return Invocation(argv=("python3", "-c", script), stdin=prompt.encode())

    result = asyncio.run(
        ScriptedClaude().run_once(
            "hi",
            RunContext(
                worktree=tmp_path,
                cwd=tmp_path,
                deadline_seconds=30,
                env_allowlist=DEFAULT_ENV_ALLOWLIST,
            ),
        )
    )

    assert result.terminal_state is TerminalState.SUCCESS
    assert result.final_response == "ok"


def test_run_once_permission_denials_make_success_failed(tmp_path):
    script = (
        "import sys;sys.stdin.read();"
        'print(\'{"type":"result","subtype":"success","is_error":false,"result":"ok",'
        '"permission_denials":[{"tool_name":"Bash","tool_use_id":"t","tool_input":{}}]}\')'
    )

    class ScriptedClaude(ClaudeCliRunner):
        command = "python3"

        def build_invocation(self, prompt, context):
            return Invocation(argv=("python3", "-c", script), stdin=prompt.encode())

    result = asyncio.run(
        ScriptedClaude().run_once(
            "hi",
            RunContext(
                worktree=tmp_path,
                cwd=tmp_path,
                deadline_seconds=30,
                env_allowlist=DEFAULT_ENV_ALLOWLIST,
            ),
        )
    )

    assert result.terminal_state is TerminalState.FAILED
    assert result.error_code == "PERMISSION_DENIED"
    assert len(result.permission_denials) == 1
