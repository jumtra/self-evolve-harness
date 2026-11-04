import asyncio
import json
from dataclasses import replace

import pytest

from seh.config import defaults
from seh.contracts import RunContext, TerminalState
from seh.runtime.agent_runner import RunnerRegistry
from seh.runtime.process import DEFAULT_ENV_ALLOWLIST
from seh.runtime.runners.antigravity_cli import AntigravityCliRunner, register
from seh.runtime.runners.base import InvalidEventStream, Invocation


def _context(tmp_path):
    return RunContext(
        worktree=tmp_path,
        cwd=tmp_path,
        deadline_seconds=30,
        env_allowlist=DEFAULT_ENV_ALLOWLIST,
    )


def _forbid_process_launch(monkeypatch):
    async def forbidden(*args, **kwargs):
        raise AssertionError("process must not be launched")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", forbidden)
    monkeypatch.setattr("seh.runtime.process.run_process", forbidden)
    monkeypatch.setattr("seh.runtime.runners.base.run_process", forbidden)


def test_disabled_run_once_is_policy_blocked_without_launching_process(tmp_path, monkeypatch):
    _forbid_process_launch(monkeypatch)

    result = asyncio.run(AntigravityCliRunner().run_once("hi", _context(tmp_path)))

    assert result.terminal_state is TerminalState.POLICY_BLOCKED
    assert result.error_code == "AGY_THIRD_PARTY_WRAPPING_NOT_PERMITTED"
    assert result.host == "antigravity"
    assert result.final_response is None
    assert result.exit_code is None
    assert result.evidence_refs == ()
    assert result.usage is None
    assert result.run_id


def test_from_config_defaults_to_disabled(tmp_path, monkeypatch):
    _forbid_process_launch(monkeypatch)

    runner = AntigravityCliRunner.from_config(defaults())
    result = asyncio.run(runner.run_once("hi", _context(tmp_path)))

    assert result.terminal_state is TerminalState.POLICY_BLOCKED


def test_from_config_reflects_enabled_value(tmp_path):
    base = defaults()
    config = replace(base, hosts=replace(base.hosts, antigravity_managed_cli="enabled"))
    script = (
        'import sys;sys.stdin.read();print(\'{"type":"result","status":"SUCCESS","result":"ok"}\')'
    )

    class ScriptedAgy(AntigravityCliRunner):
        def build_invocation(self, prompt, context):
            return Invocation(argv=("python3", "-c", script), stdin=prompt.encode())

    result = asyncio.run(ScriptedAgy.from_config(config).run_once("hi", _context(tmp_path)))

    assert result.terminal_state is TerminalState.SUCCESS


def test_build_invocation_minimal_argv_and_prompt_on_stdin(tmp_path):
    runner = AntigravityCliRunner(managed_cli="enabled")

    inv = runner.build_invocation("hello", _context(tmp_path))

    assert inv.argv == ("agy", "-p", "--output-format", "stream-json")
    assert inv.stdin == b"hello"


def test_build_invocation_appends_json_schema(tmp_path):
    schema = {"type": "object"}
    runner = AntigravityCliRunner(managed_cli="enabled", json_schema=schema)

    inv = runner.build_invocation("p", _context(tmp_path))

    assert inv.argv[4:] == ("--json-schema", json.dumps(schema))


def test_parse_events_ignores_blank_lines():
    runner = AntigravityCliRunner()

    events = runner.parse_events(b'{"type":"a"}\n\n   \n{"type":"result"}\n')

    assert events == [{"type": "a"}, {"type": "result"}]


def test_parse_events_rejects_invalid_json():
    runner = AntigravityCliRunner()

    with pytest.raises(InvalidEventStream):
        runner.parse_events(b'{"type":"a"}\nnot json\n')


def test_detect_terminal_success_with_structured_output():
    runner = AntigravityCliRunner()
    events = [
        {
            "type": "result",
            "status": "SUCCESS",
            "result": "done",
            "structured_output": {"k": 1},
        }
    ]

    decision = runner.detect_terminal(events, 0, b"")

    assert decision.state is TerminalState.SUCCESS
    assert decision.error_code is None
    assert decision.final_response == "done"
    assert decision.structured_output == {"k": 1}


@pytest.mark.parametrize("status", ["ERROR", "INVALID"])
def test_detect_terminal_error_statuses_are_failed(status):
    runner = AntigravityCliRunner()
    events = [{"type": "result", "status": status, "error": "boom"}]

    decision = runner.detect_terminal(events, 1, b"")

    assert decision.state is TerminalState.FAILED


@pytest.mark.parametrize("status", ["CANCELED", "INTERRUPTED"])
def test_detect_terminal_canceled_statuses_are_cancelled(status):
    runner = AntigravityCliRunner()
    events = [{"type": "result", "status": status}]

    decision = runner.detect_terminal(events, 1, b"")

    assert decision.state is TerminalState.CANCELLED


@pytest.mark.parametrize("status", ["WAITING", "RUNNING"])
def test_detect_terminal_non_terminal_statuses_are_invalid_output(status):
    runner = AntigravityCliRunner()
    events = [{"type": "result", "status": status}]

    decision = runner.detect_terminal(events, 0, b"")

    assert decision.state is TerminalState.INVALID_OUTPUT
    assert decision.error_code == "NOT_TERMINAL"


def test_detect_terminal_authentication_required_is_blocked_auth():
    runner = AntigravityCliRunner()
    events = [{"type": "result", "status": "ERROR", "error": "Authentication required"}]

    decision = runner.detect_terminal(events, 1, b"")

    assert decision.state is TerminalState.BLOCKED_AUTH


def test_detect_terminal_without_result_is_invalid_output():
    runner = AntigravityCliRunner()

    decision = runner.detect_terminal([{"type": "progress"}], 0, b"")

    assert decision.state is TerminalState.INVALID_OUTPUT
    assert decision.error_code == "NO_TERMINAL_EVENT"


def test_detect_terminal_converts_stderr_soft_deny_to_permission_denials():
    runner = AntigravityCliRunner()
    events = [{"type": "result", "status": "SUCCESS", "result": "ok"}]
    stderr = b"info: starting\nwarning: Permission denied for tool run_command\nbye\n"

    decision = runner.detect_terminal(events, 0, stderr)

    assert decision.permission_denials == (
        {"source": "stderr", "line": "warning: Permission denied for tool run_command"},
    )


def test_normalize_usage_reads_tokens_and_leaves_cost_unset():
    runner = AntigravityCliRunner()
    events = [
        {
            "type": "result",
            "status": "SUCCESS",
            "usage": {"input_tokens": 12, "output_tokens": 34},
        }
    ]

    usage = runner.normalize_usage(events)

    assert usage is not None
    assert usage.input_tokens == 12
    assert usage.output_tokens == 34
    assert usage.cost_usd is None


def test_normalize_usage_without_usage_is_none():
    runner = AntigravityCliRunner()

    assert runner.normalize_usage([{"type": "result", "status": "SUCCESS"}]) is None


def test_probe_spec_requires_print_output_format_and_json_schema():
    spec = AntigravityCliRunner().probe_spec()

    assert spec.command == "agy"
    assert dict(spec.required_flags) == {
        "print": ("-p",),
        "output_format": ("--output-format",),
        "json_schema": ("--json-schema",),
    }


def test_probe_when_not_installed_reports_policy_blocked_if_disabled(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda _name: None)

    report = AntigravityCliRunner().probe()

    assert report.host == "antigravity"
    assert report.installed is False
    assert report.policy_blocked is True


def test_probe_when_not_installed_is_not_blocked_if_enabled(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda _name: None)

    report = AntigravityCliRunner(managed_cli="enabled").probe()

    assert report.installed is False
    assert report.policy_blocked is False


def test_register_adds_runner_under_antigravity_host():
    registry = RunnerRegistry()

    register(registry)

    assert registry.get("antigravity").host == "antigravity"


def test_enabled_run_once_stderr_soft_deny_makes_success_failed(tmp_path):
    script = (
        "import sys;sys.stdin.read();"
        "sys.stderr.write('Permission denied: write blocked\\n');"
        'print(\'{"type":"result","status":"SUCCESS","result":"ok"}\')'
    )

    class ScriptedAgy(AntigravityCliRunner):
        command = "python3"

        def build_invocation(self, prompt, context):
            return Invocation(argv=("python3", "-c", script), stdin=prompt.encode())

    result = asyncio.run(ScriptedAgy(managed_cli="enabled").run_once("hi", _context(tmp_path)))

    assert result.terminal_state is TerminalState.FAILED
    assert result.error_code == "PERMISSION_DENIED"
    assert len(result.permission_denials) == 1
