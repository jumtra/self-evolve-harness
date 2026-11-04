from seh.runtime.agent_runner import RunnerRegistry
from seh.runtime.runners.codex_cli import CodexCliRunner, register


def test_usage_maps_tokens_and_keeps_raw_with_cost_unknown():
    runner = CodexCliRunner()
    events = runner.parse_events(
        b'{"type":"turn.completed","usage":{"input_tokens":100,"cached_input_tokens":40,'
        b'"output_tokens":20,"reasoning_output_tokens":7}}\n'
    )

    usage = runner.normalize_usage(events)

    assert usage is not None
    assert usage.input_tokens == 100
    assert usage.output_tokens == 20
    assert usage.cost_usd is None
    assert usage.raw == {
        "input_tokens": 100,
        "cached_input_tokens": 40,
        "output_tokens": 20,
        "reasoning_output_tokens": 7,
    }


def test_usage_is_none_when_turn_completed_has_no_usage():
    runner = CodexCliRunner()
    events = runner.parse_events(b'{"type":"turn.completed"}\n')

    assert runner.normalize_usage(events) is None


def test_usage_is_none_without_turn_completed():
    runner = CodexCliRunner()
    events = runner.parse_events(b'{"type":"turn.failed"}\n')

    assert runner.normalize_usage(events) is None


def test_probe_spec_requires_exec_flags():
    spec = CodexCliRunner().probe_spec()

    assert spec.command == "codex"
    assert spec.help_args == ("exec", "--help")
    assert spec.required_flags == {
        "json": ("--json",),
        "output_schema": ("--output-schema",),
        "sandbox": ("--sandbox",),
        "cd": ("--cd",),
    }


def test_register_adds_codex_runner_to_registry():
    registry = RunnerRegistry()

    register(registry)

    assert registry.get("codex").host == "codex"
