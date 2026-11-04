"""engram CLI を argv で呼ぶ Engram 実装。出力形式が不明なら ERROR（空 OK にしない）。"""

from __future__ import annotations

import asyncio
import os
import re
import shutil
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from seh.contracts.common import Result, ResultStatus
from seh.contracts.module import HealthResult, MemoryRecord
from seh.providers.memory.base import MemoryType, as_memory_type, reject_unsafe, slugify
from seh.runtime.process import DEFAULT_ENV_ALLOWLIST, ProcessResult, build_env, run_process

NOT_INSTALLED_MESSAGE = (
    "engram が見つかりません。導入方法: https://github.com/Gentleman-Programming/engram "
    '（brew install engram など）。または memory.provider = "file" を使ってください'
)
# `#<id> [<type>] <title>` の次行以降が本文。実機の出力で要確認の仮定は本パーサーに閉じ込める
_HEADER = re.compile(r"^\s*(?:\[\d+\]\s*)?#(\d+)\s+\[(\w+)\]\s+(.+?)\s*$")
_NO_RESULT = re.compile(r"no (memories|results) found", re.IGNORECASE)


class EngramMemoryProvider:
    def __init__(
        self, *, project: str, command: str = "engram", timeout_seconds: float = 30
    ) -> None:
        self._project = project
        self._command = command
        self._timeout = timeout_seconds

    def save(self, record: MemoryRecord) -> Result:
        if (rejected := reject_unsafe(record)) is not None:
            return rejected
        proc = self._call(
            ["save", record.title, record.body, "--type", record.type, "--project", self._project]
        )
        if isinstance(proc, Result):
            return proc
        return Result(ResultStatus.OK, f"{record.type}_{slugify(record.title)}")

    def search(self, query: str) -> Result:
        proc = self._call(["search", query, "--project", self._project])
        if isinstance(proc, Result):
            return proc
        text = proc.stdout.decode("utf-8", errors="replace")
        records = _parse_search(text)
        if records:
            return Result(ResultStatus.OK, records)
        if _NO_RESULT.search(text):
            return Result(ResultStatus.NOT_FOUND, message=query)
        return Result(ResultStatus.ERROR, message="engram search の出力を解析できません")

    def get(self, record_id: str) -> Result:
        return Result(ResultStatus.UNSUPPORTED, message="engram CLI に id 指定の取得がありません")

    def delete(self, record_id: str) -> Result:
        return Result(ResultStatus.UNSUPPORTED, message="engram の削除は観測 ID 指定のため未対応")

    def list(self) -> Result:
        return Result(ResultStatus.UNSUPPORTED, message="engram CLI に一覧がありません")

    def healthcheck(self) -> Result:
        if shutil.which(self._command) is None:
            return Result(
                ResultStatus.ERROR,
                HealthResult(ok=False, message=NOT_INSTALLED_MESSAGE),
                message=NOT_INSTALLED_MESSAGE,
            )
        proc = self._run(["--version"])
        ok = proc.exit_code == 0 and not proc.timed_out
        message = proc.stdout.decode("utf-8", errors="replace").strip() or f"exit {proc.exit_code}"
        return Result(
            ResultStatus.OK if ok else ResultStatus.ERROR,
            HealthResult(ok=ok, message=message),
            message=message,
        )

    def _call(self, args: list[str]) -> ProcessResult | Result:
        if shutil.which(self._command) is None:
            return Result(ResultStatus.ERROR, message=NOT_INSTALLED_MESSAGE)
        proc = self._run(args)
        if proc.timed_out:
            return Result(ResultStatus.ERROR, message="engram がタイムアウトしました")
        if proc.exit_code != 0:
            detail = proc.stderr.decode("utf-8", errors="replace").strip()
            return Result(ResultStatus.ERROR, message=f"engram が失敗しました: {detail}")
        return proc

    def _run(self, args: list[str]) -> ProcessResult:
        env = build_env(DEFAULT_ENV_ALLOWLIST, os.environ)
        argv = [self._command, *args]
        with ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(
                asyncio.run,
                run_process(argv, cwd=Path.cwd(), env=env, timeout_seconds=self._timeout),
            ).result()


def _parse_search(text: str) -> list[MemoryRecord]:
    records: list[MemoryRecord] = []
    current: tuple[str, MemoryType, str] | None = None
    body: list[str] = []

    def flush() -> None:
        if current is None:
            return
        obs_id, kind, title = current
        records.append(
            MemoryRecord(
                id=f"{kind}_{slugify(title)}",
                type=kind,
                title=title,
                body="\n".join(body).strip(),
                metadata={"engram_id": obs_id},
            )
        )

    for line in text.splitlines():
        match = _HEADER.match(line)
        kind = as_memory_type(match.group(2)) if match else None
        if match and kind is not None:
            flush()
            current = (match.group(1), kind, match.group(3))
            body = []
        elif current is not None:
            body.append(line.strip())
    flush()
    return records
