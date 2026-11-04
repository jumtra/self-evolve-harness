from pathlib import Path

import pytest

from seh.contracts import RunContext
from seh.runtime.runners.codex_cli import CodexCliRunner


def test_default_argv_uses_workspace_write_and_stdin_dash(tmp_path):
    context = RunContext(worktree=tmp_path, cwd=tmp_path, deadline_seconds=10, env_allowlist=())

    invocation = CodexCliRunner().build_invocation("do it", context)

    assert invocation.argv == (
        "codex",
        "exec",
        "--json",
        "-C",
        str(tmp_path),
        "-s",
        "workspace-write",
        "--skip-git-repo-check",
        "-",
    )


def test_read_only_sandbox_is_passed_through(tmp_path):
    context = RunContext(worktree=tmp_path, cwd=tmp_path, deadline_seconds=10, env_allowlist=())

    invocation = CodexCliRunner(sandbox="read-only").build_invocation("do it", context)

    assert invocation.argv[invocation.argv.index("-s") + 1] == "read-only"


def test_output_schema_is_inserted_before_stdin_dash(tmp_path):
    context = RunContext(worktree=tmp_path, cwd=tmp_path, deadline_seconds=10, env_allowlist=())
    schema = Path("/tmp/schema.json")

    invocation = CodexCliRunner(output_schema_path=schema).build_invocation("do it", context)

    assert invocation.argv[-3:] == ("--output-schema", str(schema), "-")


def test_prompt_goes_to_stdin_not_argv(tmp_path):
    context = RunContext(worktree=tmp_path, cwd=tmp_path, deadline_seconds=10, env_allowlist=())

    invocation = CodexCliRunner().build_invocation("secret prompt", context)

    assert invocation.stdin == b"secret prompt"
    assert all("secret prompt" not in arg for arg in invocation.argv)


@pytest.mark.parametrize("sandbox", ["danger-full-access", "", "--dangerously-bypass"])
def test_forbidden_sandbox_raises_value_error(sandbox):
    with pytest.raises(ValueError):
        CodexCliRunner(sandbox=sandbox)
