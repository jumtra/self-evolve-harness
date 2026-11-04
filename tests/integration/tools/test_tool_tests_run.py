from pathlib import Path

import pytest

from seh.policy import Policy
from seh.tools.registry import ToolContext, ToolError, default_registry

_ALL_TOOLS = frozenset({"tests.run"})
_EXEC = frozenset({"exec:tests"})


async def test_allowed_command_passes(tmp_path: Path):
    ctx = ToolContext(
        root=tmp_path,
        policy=Policy(tool_allowlist=_ALL_TOOLS, command_allowlist=frozenset({"python3"})),
        granted_permissions=_EXEC,
    )

    result = await default_registry().execute(
        "tests.run", {"argv": ["python3", "-c", "import sys; sys.exit(0)"]}, ctx
    )

    assert result["passed"] is True
    assert result["exit_code"] == 0
    assert result["timed_out"] is False


async def test_nonzero_exit_is_not_passed(tmp_path: Path):
    ctx = ToolContext(
        root=tmp_path,
        policy=Policy(tool_allowlist=_ALL_TOOLS, command_allowlist=frozenset({"python3"})),
        granted_permissions=_EXEC,
    )

    result = await default_registry().execute(
        "tests.run", {"argv": ["python3", "-c", "import sys; sys.exit(3)"]}, ctx
    )

    assert result["passed"] is False
    assert result["exit_code"] == 3


async def test_command_outside_allowlist_is_not_authorized(tmp_path: Path):
    ctx = ToolContext(
        root=tmp_path,
        policy=Policy(tool_allowlist=_ALL_TOOLS, command_allowlist=frozenset({"python3"})),
        granted_permissions=_EXEC,
    )

    with pytest.raises(ToolError) as exc:
        await default_registry().execute("tests.run", {"argv": ["ls"]}, ctx)

    assert exc.value.code == "NOT_AUTHORIZED"


async def test_timeout_is_reported(tmp_path: Path):
    ctx = ToolContext(
        root=tmp_path,
        policy=Policy(tool_allowlist=_ALL_TOOLS, command_allowlist=frozenset({"python3"})),
        granted_permissions=_EXEC,
        timeout_seconds=0.5,
    )

    result = await default_registry().execute(
        "tests.run", {"argv": ["python3", "-c", "import time; time.sleep(30)"]}, ctx
    )

    assert result["timed_out"] is True
    assert result["passed"] is False


async def test_output_is_masked(tmp_path: Path):
    secret = "sk-ant-" + "api03-" + "B" * 30
    ctx = ToolContext(
        root=tmp_path,
        policy=Policy(tool_allowlist=_ALL_TOOLS, command_allowlist=frozenset({"python3"})),
        granted_permissions=_EXEC,
    )

    result = await default_registry().execute(
        "tests.run",
        {"argv": ["python3", "-c", "print(" + repr(secret) + ")"]},
        ctx,
    )

    assert secret not in str(result["stdout_tail"])
    assert result["passed"] is True


async def test_cwd_escaping_root_is_invalid_input(tmp_path: Path):
    ctx = ToolContext(
        root=tmp_path,
        policy=Policy(tool_allowlist=_ALL_TOOLS, command_allowlist=frozenset({"python3"})),
        granted_permissions=_EXEC,
    )

    with pytest.raises(ToolError) as exc:
        await default_registry().execute(
            "tests.run", {"argv": ["python3", "-c", "pass"], "cwd": ".."}, ctx
        )

    assert exc.value.code == "INVALID_INPUT"
