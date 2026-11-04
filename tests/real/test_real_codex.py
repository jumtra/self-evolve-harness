import os
import subprocess

import pytest

from seh.contracts import RunContext, TerminalState
from seh.runtime.runners.codex_cli import CodexCliRunner

pytestmark = pytest.mark.real


@pytest.mark.skipif(os.environ.get("SEH_REAL_SMOKE") != "1", reason="SEH_REAL_SMOKE=1 が必要")
async def test_real_codex_reads_first_line_of_readme(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / "README.md").write_text("hello smoke\nsecond line\n")
    context = RunContext(
        worktree=tmp_path,
        cwd=tmp_path,
        deadline_seconds=300,
        env_allowlist=("PATH", "HOME", "OPENAI_API_KEY", "CODEX_HOME"),
    )

    result = await CodexCliRunner(sandbox="read-only").run_once(
        "README.md の1行目を出力して終了", context
    )

    if result.terminal_state is TerminalState.BLOCKED_AUTH:
        pytest.skip("codex 未認証")
    assert result.terminal_state is TerminalState.SUCCESS, result
