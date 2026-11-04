from __future__ import annotations

from seh.runtime.agent_runner import RunnerRegistry
from seh.runtime.runners import antigravity_cli, claude_cli, codex_cli, opencode_cli


def default_registry() -> RunnerRegistry:
    registry = RunnerRegistry()
    claude_cli.register(registry)
    codex_cli.register(registry)
    opencode_cli.register(registry)
    # 利用条件の確認が取れていないので Managed 実行は常に POLICY_BLOCKED（FR-093）
    antigravity_cli.register(registry, managed_cli="disabled")
    return registry
