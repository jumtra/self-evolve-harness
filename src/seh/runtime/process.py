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


class _Capture:
    """キャンセルされても部分出力を失わないための受け皿。"""

    def __init__(self) -> None:
        self.data = bytearray()
        self.truncated = False


async def _drain(stream: asyncio.StreamReader | None, limit: int, cap: _Capture) -> None:
    # 上限超過後も読み続けて子のパイプ詰まりを防ぐ
    if stream is None:
        return
    while chunk := await stream.read(_READ_CHUNK):
        room = limit - len(cap.data)
        if room > 0:
            cap.data.extend(chunk[:room])
        if len(chunk) > room:
            cap.truncated = True


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

    out_buf = _Capture()
    err_buf = _Capture()

    async def communicate() -> None:
        drains = asyncio.gather(
            _drain(proc.stdout, max_output_bytes, out_buf),
            _drain(proc.stderr, max_output_bytes, err_buf),
            feed(),
        )
        # Process.wait() は全パイプが閉じるまで戻らないため、returncode を直接ポーリングする
        while proc.returncode is None and not drains.done():
            await asyncio.sleep(0.02)
        # 孫がパイプを保持し続けると EOF が来ないため、リーダー終了後の drain は猶予付きにする
        try:
            await asyncio.wait_for(asyncio.shield(drains), kill_grace_seconds)
        except TimeoutError:
            _signal_group(proc.pid, signal.SIGKILL)
            drains.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await drains
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(proc.wait(), kill_grace_seconds)

    timed_out = False
    cancelled = False
    reader = asyncio.ensure_future(communicate())
    try:
        await asyncio.wait_for(asyncio.shield(reader), timeout_seconds)
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
            # kill 後は EOF で drain が完了するので部分出力も保持する。上限付きで無期限待ちを避ける
            await asyncio.wait_for(reader, kill_grace_seconds + 1)

    return ProcessResult(
        argv_digest=digest,
        exit_code=proc.returncode,
        stdout=bytes(out_buf.data),
        stderr=bytes(err_buf.data),
        timed_out=timed_out,
        cancelled=cancelled,
        stdout_truncated=out_buf.truncated,
        stderr_truncated=err_buf.truncated,
        duration_seconds=time.monotonic() - start,
    )
