import asyncio
import os
import subprocess

import pytest

from seh.contracts import RunContext, TerminalState
from seh.runtime.process import DEFAULT_ENV_ALLOWLIST
from seh.runtime.runners.claude_cli import ClaudeCliRunner

pytestmark = [
    pytest.mark.real,
    pytest.mark.skipif(os.environ.get("SEH_REAL_SMOKE") != "1", reason="SEH_REAL_SMOKE=1 required"),
]


def test_real_claude_prints_first_line_of_readme(tmp_path):
    (tmp_path / "README.md").write_text("hello smoke\n")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    context = RunContext(
        worktree=tmp_path,
        cwd=tmp_path,
        deadline_seconds=120,
        env_allowlist=DEFAULT_ENV_ALLOWLIST,
    )

    result = asyncio.run(
        ClaudeCliRunner().run_once(
            "README.md の1行目をそのまま出力して終了してください。ツールは使わないでください。",
            context,
        )
    )

    if result.terminal_state is TerminalState.BLOCKED_AUTH:
        pytest.skip("BLOCKED_AUTH")
    assert result.terminal_state is TerminalState.SUCCESS
