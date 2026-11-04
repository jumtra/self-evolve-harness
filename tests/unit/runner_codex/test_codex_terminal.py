import pytest

from seh.contracts import TerminalState
from seh.runtime.runners.base import InvalidEventStream
from seh.runtime.runners.codex_cli import CodexCliRunner


def test_parse_events_ignores_blank_lines():
    stdout = b'{"type":"turn.started"}\n\n  \n{"type":"turn.completed"}\n'

    events = CodexCliRunner().parse_events(stdout)

    assert [e["type"] for e in events] == ["turn.started", "turn.completed"]


def test_parse_events_rejects_invalid_json_line():
    with pytest.raises(InvalidEventStream):
        CodexCliRunner().parse_events(b'{"type":"turn.started"}\nnot json\n')


def test_parse_events_rejects_non_object_line():
    with pytest.raises(InvalidEventStream):
        CodexCliRunner().parse_events(b"[1, 2]\n")


def test_turn_completed_is_success_with_last_agent_message_as_final_response():
    runner = CodexCliRunner()
    events = runner.parse_events(
        b'{"type":"item.completed","item":{"type":"agent_message","text":"first"}}\n'
        b'{"type":"item.completed","item":{"type":"command_execution","text":"ls"}}\n'
        b'{"type":"item.completed","item":{"type":"agent_message","text":"done"}}\n'
        b'{"type":"turn.completed","usage":{"input_tokens":10,"output_tokens":5}}\n'
    )

    decision = runner.detect_terminal(events, 0, b"")

    assert decision.state is TerminalState.SUCCESS
    assert decision.error_code is None
    assert decision.final_response == "done"


def test_agent_message_content_string_is_accepted():
    runner = CodexCliRunner()
    events = runner.parse_events(
        b'{"type":"item.completed","item":{"type":"agent_message","content":"via content"}}\n'
        b'{"type":"turn.completed"}\n'
    )

    decision = runner.detect_terminal(events, 0, b"")

    assert decision.final_response == "via content"


def test_unexpected_agent_message_shape_gives_none_final_response():
    runner = CodexCliRunner()
    events = runner.parse_events(
        b'{"type":"item.completed","item":{"type":"agent_message","content":[{"x":1}]}}\n'
        b'{"type":"turn.completed"}\n'
    )

    decision = runner.detect_terminal(events, 0, b"")

    assert decision.state is TerminalState.SUCCESS
    assert decision.final_response is None


def test_turn_failed_is_failed_without_leaking_message():
    runner = CodexCliRunner()
    events = runner.parse_events(b'{"type":"turn.failed","error":{"message":"boom detail"}}\n')

    decision = runner.detect_terminal(events, 1, b"")

    assert decision.state is TerminalState.FAILED
    assert decision.error_code == "TURN_FAILED"
    assert decision.final_response is None


def test_error_event_is_failed_with_codex_error_code():
    runner = CodexCliRunner()
    events = runner.parse_events(b'{"type":"error","message":"bad thing"}\n')

    decision = runner.detect_terminal(events, 1, b"")

    assert decision.state is TerminalState.FAILED
    assert decision.error_code == "CODEX_ERROR"
    assert decision.final_response is None


def test_missing_terminal_event_is_invalid_output():
    runner = CodexCliRunner()
    events = runner.parse_events(b'{"type":"turn.started"}\n')

    decision = runner.detect_terminal(events, 0, b"")

    assert decision.state is TerminalState.INVALID_OUTPUT
    assert decision.error_code == "NO_TERMINAL_EVENT"


@pytest.mark.parametrize(
    "marker", ["please login first", "Auth failed", "missing API key", "HTTP 401"]
)
def test_nonzero_exit_with_auth_stderr_is_blocked_auth(marker):
    runner = CodexCliRunner()

    decision = runner.detect_terminal([], 1, marker.encode())

    assert decision.state is TerminalState.BLOCKED_AUTH
    assert decision.error_code == "AUTH_SUSPECTED"


def test_auth_stderr_with_zero_exit_is_not_blocked_auth():
    runner = CodexCliRunner()
    events = runner.parse_events(b'{"type":"turn.completed"}\n')

    decision = runner.detect_terminal(events, 0, b"login hint in warnings")

    assert decision.state is TerminalState.SUCCESS


def test_output_schema_puts_parsed_final_response_in_structured_output(tmp_path):
    runner = CodexCliRunner(output_schema_path=tmp_path / "s.json")
    events = runner.parse_events(
        b'{"type":"item.completed","item":{"type":"agent_message","text":"{\\"ok\\": true}"}}\n'
        b'{"type":"turn.completed"}\n'
    )

    decision = runner.detect_terminal(events, 0, b"")

    assert decision.state is TerminalState.SUCCESS
    assert decision.structured_output == {"ok": True}


def test_output_schema_with_unparsable_final_response_is_invalid_output(tmp_path):
    runner = CodexCliRunner(output_schema_path=tmp_path / "s.json")
    events = runner.parse_events(
        b'{"type":"item.completed","item":{"type":"agent_message","text":"not json"}}\n'
        b'{"type":"turn.completed"}\n'
    )

    decision = runner.detect_terminal(events, 0, b"")

    assert decision.state is TerminalState.INVALID_OUTPUT
    assert decision.error_code == "STRUCTURED_OUTPUT_INVALID"
