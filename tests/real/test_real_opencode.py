import os
import subprocess

import pytest

from seh.contracts import RunContext, TerminalState
from seh.runtime.runners.opencode_cli import OpenCodeCliRunner

pytestmark = [
    pytest.mark.real,
    pytest.mark.skipif(os.environ.get("SEH_REAL_SMOKE") != "1", reason="SEH_REAL_SMOKE=1 required"),
]


async def test_real_opencode_prints_first_line_of_readme(tmp_path):
    (tmp_path / "README.md").write_text("hello-seh-smoke\nsecond line\n")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    context = RunContext(tmp_path, tmp_path, 180, ("PATH", "HOME"))

    result = await OpenCodeCliRunner().run_once(
        "Print the first line of README.md and exit.", context
    )

    assert result.terminal_state is TerminalState.SUCCESS, f"terminal_state={result.terminal_state}"
    assert result.final_response and "hello-seh-smoke" in result.final_response
