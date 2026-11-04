from __future__ import annotations

from seh.runtime.agent_runner import RunnerRegistry
from seh.runtime.runners import claude_cli, codex_cli, opencode_cli


def default_registry() -> RunnerRegistry:
    registry = RunnerRegistry()
    claude_cli.register(registry)
    codex_cli.register(registry)
    opencode_cli.register(registry)
    return registry
