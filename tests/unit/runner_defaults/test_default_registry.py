from seh.runtime.runners.claude_cli import ClaudeCliRunner
from seh.runtime.runners.codex_cli import CodexCliRunner
from seh.runtime.runners.defaults import default_registry
from seh.runtime.runners.opencode_cli import OpenCodeCliRunner


def test_default_registry_registers_cli_runners_for_three_hosts() -> None:
    registry = default_registry()

    assert isinstance(registry.get("claude"), ClaudeCliRunner)
    assert isinstance(registry.get("codex"), CodexCliRunner)
    assert isinstance(registry.get("opencode"), OpenCodeCliRunner)


def test_eval_command_uses_default_registry_with_claude_runner() -> None:
    from seh.commands import eval as eval_command

    assert isinstance(eval_command.REGISTRY.get("claude"), ClaudeCliRunner)
