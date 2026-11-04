"""公式 CLI を安全に起動する subprocess 層（shell 非経由・プロセスグループ kill）。"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import os
import signal
import time
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

DEFAULT_ENV_ALLOWLIST = (
    "PATH",
    "HOME",
    "LANG",
    "LC_ALL",
    "TERM",
    "USER",
    "LOGNAME",
    "SHELL",
    "TMPDIR",
    "XDG_CONFIG_HOME",
    "XDG_DATA_HOME",
    "XDG_CACHE_HOME",
)

_READ_CHUNK = 65536


@dataclass(frozen=True)
class ProcessResult:
    argv_digest: str
    exit_code: int | None
    stdout: bytes
    stderr: bytes
    timed_out: bool
    cancelled: bool
    stdout_truncated: bool
    stderr_truncated: bool
    duration_seconds: float


def _is_blocked_key(key: str) -> bool:
    # ホスト側 CLI のネスト実行判定・セッション状態を子へ漏らさない
    return key == "CLAUDECODE" or key.startswith("CLAUDE_CODE_")


def build_env(
    allowlist: Iterable[str],
    source: Mapping[str, str],
    extra: Mapping[str, str] | None = None,
) -> dict[str, str]:
    env = {k: source[k] for k in allowlist if k in source}
    if extra:
        env.update(extra)
    return {k: v for k, v in env.items() if not _is_blocked_key(k)}


async def _drain(stream: asyncio.StreamReader | None, limit: int) -> tuple[bytes, bool]:
    # 上限超過後も読み続けて子のパイプ詰まりを防ぐ
    buf = bytearray()
    truncated = False
    if stream is None:
        return b"", False
    while chunk := await stream.read(_READ_CHUNK):
        room = limit - len(buf)
        if room > 0:
            buf.extend(chunk[:room])
        if len(chunk) > room:
            truncated = True
    return bytes(buf), truncated


def _signal_group(pgid: int, sig: signal.Signals) -> None:
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(pgid, sig)


def _group_alive(pgid: int) -> bool:
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


async def _terminate_group(proc: asyncio.subprocess.Process, grace: float) -> None:
    pgid = proc.pid  # start_new_session=True により pid == pgid
    _signal_group(pgid, signal.SIGTERM)
    deadline = time.monotonic() + grace
    while time.monotonic() < deadline:
        if proc.returncode is not None and not _group_alive(pgid):
            break
        await asyncio.sleep(0.02)
    # リーダーが終了済みでも孫が残りうるので常にグループへ SIGKILL
    _signal_group(pgid, signal.SIGKILL)
    await asyncio.shield(proc.wait())
    for _ in range(100):
        if not _group_alive(pgid):
            break
        await asyncio.sleep(0.02)


async def run_process(
    argv: Sequence[str],
    *,
    cwd: Path,
    env: Mapping[str, str],
    stdin: bytes | None = None,
    timeout_seconds: float,
    max_output_bytes: int = 10_000_000,
    kill_grace_seconds: float = 2.0,
) -> ProcessResult:
    if not argv or not all(isinstance(a, str) for a in argv):
        raise ValueError("argv must be a non-empty sequence of str")

    digest = hashlib.sha256("\0".join(argv).encode()).hexdigest()
    start = time.monotonic()
    proc = await asyncio.create_subprocess_exec(
        *argv,
        cwd=cwd,
        env=dict(env),
        stdin=asyncio.subprocess.PIPE if stdin is not None else asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        start_new_session=True,
    )

    async def feed() -> None:
        if proc.stdin is None or stdin is None:
            return
        try:
            proc.stdin.write(stdin)
            await proc.stdin.drain()
            proc.stdin.close()
        except (BrokenPipeError, ConnectionResetError):
            pass

    async def communicate() -> tuple[tuple[bytes, bool], tuple[bytes, bool]]:
        out, err, _ = await asyncio.gather(
            _drain(proc.stdout, max_output_bytes),
            _drain(proc.stderr, max_output_bytes),
            feed(),
        )
        await proc.wait()
        return out, err

    timed_out = False
    cancelled = False
    out: tuple[bytes, bool] = (b"", False)
    err: tuple[bytes, bool] = (b"", False)
    reader = asyncio.ensure_future(communicate())
    try:
        out, err = await asyncio.wait_for(asyncio.shield(reader), timeout_seconds)
    except TimeoutError:
        timed_out = True
    except asyncio.CancelledError:
        cancelled = True
        raise
    finally:
        # 正常終了時も孫の取り残しを掃除するため無条件でグループを終了させる
        if timed_out or cancelled or _group_alive(proc.pid):
            await _terminate_group(proc, kill_grace_seconds)
        if not reader.done():
            reader.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            # kill 後は EOF で drain が完了するので、タイムアウト前の部分出力も保持する
            out, err = await reader

    return ProcessResult(
        argv_digest=digest,
        exit_code=proc.returncode,
        stdout=out[0],
        stderr=err[0],
        timed_out=timed_out,
        cancelled=cancelled,
        stdout_truncated=out[1],
        stderr_truncated=err[1],
        duration_seconds=time.monotonic() - start,
    )
