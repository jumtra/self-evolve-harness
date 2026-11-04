import asyncio
import os
import sys
from pathlib import Path

import pytest

from seh.runtime.process import run_process


async def test_run_process_captures_exit_code_and_separate_streams(tmp_path: Path):
    code = "import sys; sys.stdout.write('out'); sys.stderr.write('err'); sys.exit(3)"

    result = await run_process(
        [sys.executable, "-c", code],
        cwd=tmp_path,
        env=dict(os.environ),
        timeout_seconds=10,
    )

    assert result.exit_code == 3
    assert result.stdout == b"out"
    assert result.stderr == b"err"
    assert not result.timed_out
    assert not result.cancelled
    assert len(result.argv_digest) == 64


async def test_run_process_passes_stdin(tmp_path: Path):
    code = "import sys; sys.stdout.write(sys.stdin.read().upper())"

    result = await run_process(
        [sys.executable, "-c", code],
        cwd=tmp_path,
        env=dict(os.environ),
        stdin=b"hello",
        timeout_seconds=10,
    )

    assert result.stdout == b"HELLO"


async def test_run_process_does_not_expand_shell_metacharacters(tmp_path: Path):
    arg = "a; echo injected $(whoami) `id`"

    result = await run_process(
        ["echo", arg],
        cwd=tmp_path,
        env=dict(os.environ),
        timeout_seconds=10,
    )

    assert result.stdout == (arg + "\n").encode()


async def test_run_process_timeout_kills_process_group_including_grandchildren(tmp_path: Path):
    pidfile = tmp_path / "pgid"
    script = f"echo $$ > {pidfile}; sleep 100 & sleep 100; wait"

    result = await run_process(
        ["sh", "-c", script],
        cwd=tmp_path,
        env=dict(os.environ),
        timeout_seconds=0.5,
        kill_grace_seconds=1.0,
    )

    pgid = int(pidfile.read_text().strip())
    assert result.timed_out
    assert result.exit_code is None or result.exit_code < 0
    with pytest.raises(ProcessLookupError):
        os.killpg(pgid, 0)


async def test_run_process_cancel_propagates_and_kills_group(tmp_path: Path):
    pidfile = tmp_path / "pgid"
    script = f"echo $$ > {pidfile}; sleep 100 & sleep 100; wait"
    task = asyncio.create_task(
        run_process(
            ["sh", "-c", script],
            cwd=tmp_path,
            env=dict(os.environ),
            timeout_seconds=60,
            kill_grace_seconds=1.0,
        )
    )
    for _ in range(100):
        if pidfile.exists() and pidfile.read_text().strip():
            break
        await asyncio.sleep(0.05)

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    pgid = int(pidfile.read_text().strip())
    with pytest.raises(ProcessLookupError):
        os.killpg(pgid, 0)


async def test_run_process_truncates_large_output_without_deadlock(tmp_path: Path):
    code = "import sys; sys.stdout.write('a' * 3_000_000); sys.stderr.write('b' * 3_000_000)"

    result = await run_process(
        [sys.executable, "-c", code],
        cwd=tmp_path,
        env=dict(os.environ),
        timeout_seconds=20,
        max_output_bytes=1000,
    )

    assert result.exit_code == 0
    assert len(result.stdout) == 1000
    assert len(result.stderr) == 1000
    assert result.stdout_truncated
    assert result.stderr_truncated


async def test_run_process_missing_executable_raises(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        await run_process(
            ["definitely-not-a-real-binary-xyz"],
            cwd=tmp_path,
            env=dict(os.environ),
            timeout_seconds=5,
        )


@pytest.mark.parametrize("argv", [[], [1], ["a", None]])
async def test_run_process_rejects_invalid_argv(tmp_path: Path, argv: list):
    with pytest.raises(ValueError):
        await run_process(argv, cwd=tmp_path, env={}, timeout_seconds=5)


async def test_run_process_returns_early_when_grandchild_holds_pipes(tmp_path: Path):
    import time

    start = time.monotonic()

    result = await run_process(
        ["sh", "-c", "sleep 30 & echo done"],
        cwd=tmp_path,
        env=dict(os.environ),
        timeout_seconds=20,
        kill_grace_seconds=1.0,
    )

    assert result.exit_code == 0
    assert not result.timed_out
    assert b"done" in result.stdout
    assert time.monotonic() - start < 3.0
    leftover = await asyncio.create_subprocess_exec(
        "pgrep", "-f", "sleep 30", stdout=asyncio.subprocess.PIPE
    )
    out, _ = await leftover.communicate()
    assert out.strip() == b""
