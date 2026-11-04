from pathlib import Path

import pytest

from seh.contracts import RunContext, TerminalState
from seh.runtime.runners.claude_cli import ClaudeCliRunner
from seh.runtime.runners.codex_cli import CodexCliRunner
from seh.runtime.runners.opencode_cli import OpenCodeCliRunner


def test_codex_read_only_context_overrides_default_write_sandbox(tmp_path: Path) -> None:
    context = RunContext(tmp_path, tmp_path, 10, (), permissions_profile="read-only")
    invocation = CodexCliRunner().build_invocation("plan", context)
    assert invocation.argv[invocation.argv.index("-s") + 1] == "read-only"


@pytest.mark.parametrize("runner", [ClaudeCliRunner(), OpenCodeCliRunner()])
async def test_unverified_read_only_runner_does_not_start_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, runner: ClaudeCliRunner | OpenCodeCliRunner
) -> None:
    async def forbidden(*args: object) -> None:
        raise AssertionError("process must not start")

    monkeypatch.setattr(runner, "_execute", forbidden)
    result = await runner.run_once(
        "plan", RunContext(tmp_path, tmp_path, 10, (), permissions_profile="read-only")
    )
    assert result.terminal_state is TerminalState.UNSUPPORTED
    assert result.error_code == "READ_ONLY_UNSUPPORTED"
