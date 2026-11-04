"""CodeGraph CLI(colbymchenry/codegraph)を CodeIntelligenceProvider 契約へ写像する。

`--json` は各サブコマンドの `--help` を probe して対応を確認した場合だけ使う。
出力が解釈できないときは空の OK にせず ERROR を返す。自動インストールはしない。
"""

from __future__ import annotations

import asyncio
import json
import os
import re
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path, PurePosixPath
from typing import Any

from seh.contracts.common import Result, ResultStatus
from seh.contracts.module import HealthResult
from seh.providers.codeintel.base import CodeIntelError, Impact, Symbol
from seh.redaction import mask_text
from seh.runtime.process import DEFAULT_ENV_ALLOWLIST, ProcessResult, build_env, run_process

INSTALL_HINT = (
    "codegraph が見つかりません。`npm i -g @colbymchenry/codegraph` で導入してください"
    "（seh は自動インストールしません）"
)
INDEX_MISSING = "INDEX_MISSING: seh を通じて index を実行してください"

_ANSI = re.compile(r"\x1b\[[0-9;]*m")
_NOT_FOUND = re.compile(r"no results found|not found|no test files affected", re.IGNORECASE)
_TEXT_ENTRY = re.compile(r"^(\w+)\s+(\S.*)$")
_TEXT_LOCATION = re.compile(r"^\s+(.+):(\d+)$")
_KINDS = frozenset({"function", "class", "method", "variable"})
_TEST_PATTERNS = (
    re.compile(r"(^|/)test_[^/]*\.py$"),
    re.compile(r"_test\.py$"),
    re.compile(r"\.test\.ts$"),
    re.compile(r"\.spec\.ts$"),
    re.compile(r"_test\.go$"),
    re.compile(r"(^|/)tests/"),
)


class _NoMatch(Exception):
    """終了コード 0 だが該当なし。"""


def _strip_ansi(text: str) -> str:
    return _ANSI.sub("", text)


def _kind(raw: object) -> str:
    return raw if isinstance(raw, str) and raw in _KINDS else "unknown"


def _is_test_path(path: str) -> bool:
    return any(p.search(path) for p in _TEST_PATTERNS)


class CodeGraphProvider:
    name = "codegraph"

    def __init__(
        self,
        root: Path,
        *,
        command: str = "codegraph",
        home: Path | None = None,
        timeout_seconds: float = 120,
    ) -> None:
        self._root = root
        self._command = command
        self._timeout = timeout_seconds
        # NO_COLOR は ANSI 装飾を避けてテキストパースを安定させるため
        extra = {"NO_COLOR": "1"}
        if home is not None:
            extra["HOME"] = str(home)
        self._env = build_env(DEFAULT_ENV_ALLOWLIST, os.environ, extra)
        self._json: dict[str, bool] = {}

    def json_supported(self, subcommand: str) -> bool:
        if subcommand not in self._json:
            proc = self._exec([subcommand, "--help"])
            text = proc.stdout.decode("utf-8", errors="replace")
            self._json[subcommand] = proc.exit_code == 0 and "--json" in text
        return self._json[subcommand]

    def index(self, root: Path) -> Result:
        sub = "sync" if (root / ".codegraph").is_dir() else "init"
        return self._guard(lambda: self._ok_after(self._checked([sub, str(root)], sub)))

    def search_symbols(self, query: str) -> Result:
        return self._guard(lambda: self._search(query))

    def dependencies(self, symbol: str) -> Result:
        return self._guard(lambda: self._dependencies(symbol))

    def change_impact(self, paths: list[str]) -> Result:
        return self._guard(lambda: self._change_impact(paths))

    def affected_tests(self, paths: list[str]) -> Result:
        return self._guard(lambda: self._affected_tests(paths))

    def healthcheck(self) -> Result:
        def check() -> Result:
            proc = self._checked(["--version"], "--version")
            version = proc.stdout.decode("utf-8", errors="replace").strip()
            message = f"codegraph {version}"
            return Result(ResultStatus.OK, HealthResult(ok=True, message=message), message=message)

        return self._guard(check)

    def _guard(self, action: Callable[[], Result]) -> Result:
        try:
            return action()
        except _NoMatch as exc:
            return Result(ResultStatus.NOT_FOUND, message=str(exc))
        except CodeIntelError as exc:
            return Result(ResultStatus.ERROR, message=str(exc))

    def _ok_after(self, _proc: ProcessResult) -> Result:
        return Result(ResultStatus.OK)

    def _exec(self, args: list[str]) -> ProcessResult:
        argv = [self._command, *args]
        try:
            with ThreadPoolExecutor(max_workers=1) as pool:
                return pool.submit(
                    asyncio.run,
                    run_process(argv, cwd=self._root, env=self._env, timeout_seconds=self._timeout),
                ).result()
        except FileNotFoundError as exc:
            raise CodeIntelError(INSTALL_HINT) from exc
        except OSError as exc:
            raise CodeIntelError(f"codegraph の起動に失敗: {mask_text(str(exc))}") from exc

    def _checked(self, args: list[str], label: str) -> ProcessResult:
        proc = self._exec(args)
        if proc.timed_out:
            raise CodeIntelError(f"codegraph {label} timed out")
        if proc.exit_code != 0:
            detail = proc.stderr or proc.stdout
            text = mask_text(_strip_ansi(detail.decode("utf-8", errors="replace")).strip())
            raise CodeIntelError(f"codegraph {label} failed (exit {proc.exit_code}): {text}")
        return proc

    def _query(self, sub: str, args: list[str]) -> tuple[ProcessResult, bool]:
        """(proc, json_mode)。index 未作成は起動せず INDEX_MISSING を返す。"""
        if not (self._root / ".codegraph").is_dir():
            raise CodeIntelError(INDEX_MISSING)
        use_json = self.json_supported(sub)
        flags = ["--json"] if use_json else []
        return self._checked([sub, *flags, *args], sub), use_json

    def _search(self, query: str) -> Result:
        proc, use_json = self._query("query", [query])
        out = proc.stdout.decode("utf-8", errors="replace")
        if use_json:
            symbols = self._json_symbols(out)
        else:
            symbols = [
                Symbol(name, _kind(kind), self._norm(path), line)
                for kind, name, path, line in _text_entries(out)
            ]
        if not symbols:
            self._empty_or_error(out)
        unique = sorted(set(symbols), key=lambda s: (s.path, s.line, s.name))
        return Result(ResultStatus.OK, tuple(unique))

    def _json_symbols(self, out: str) -> list[Symbol]:
        data = self._load_json(out)
        if not isinstance(data, list):
            raise CodeIntelError("codegraph query: 想定外の JSON 形式")
        try:
            return [
                Symbol(
                    str(item["node"]["name"]),
                    _kind(item["node"].get("kind")),
                    self._norm(item["node"]["filePath"]),
                    int(item["node"]["startLine"]),
                )
                for item in data
            ]
        except (KeyError, TypeError, ValueError) as exc:
            raise CodeIntelError("codegraph query: 想定外の JSON 形式") from exc

    def _dependencies(self, symbol: str) -> Result:
        paths: set[str] = set()
        for sub, key in (("callers", "callers"), ("callees", "callees")):
            proc, use_json = self._query(sub, [symbol])
            out = proc.stdout.decode("utf-8", errors="replace")
            if use_json:
                paths |= self._json_paths(out, key)
            else:
                paths |= {self._norm(p) for _, _, p, _ in _text_entries(out)}
        if not paths:
            raise _NoMatch(f"no dependencies: {symbol}")
        return Result(ResultStatus.OK, tuple(sorted(paths)))

    def _json_paths(self, out: str, key: str) -> set[str]:
        if _NOT_FOUND.search(out) and not out.lstrip().startswith("{"):
            return set()
        data = self._load_json(out)
        try:
            return {self._norm(item["filePath"]) for item in data[key]}
        except (KeyError, TypeError) as exc:
            raise CodeIntelError(f"codegraph {key}: 想定外の JSON 形式") from exc

    def _affected(self, paths: list[str]) -> list[str]:
        proc, use_json = self._query("affected", [self._norm(p) for p in paths])
        out = proc.stdout.decode("utf-8", errors="replace")
        if use_json:
            data = self._load_json(out)
            try:
                return [self._norm(p) for p in data["affectedTests"]]
            except (KeyError, TypeError) as exc:
                raise CodeIntelError("codegraph affected: 想定外の JSON 形式") from exc
        return self._text_paths(out)

    def _text_paths(self, out: str) -> list[str]:
        lines = [ln.strip() for ln in _strip_ansi(out).splitlines() if ln.strip()]
        if any(_NOT_FOUND.search(ln) for ln in lines):
            return []
        if any(" " in ln or ln[0] in "ℹ✗●│└" for ln in lines):
            raise CodeIntelError("codegraph affected: 出力を解釈できません")
        return [self._norm(ln) for ln in lines]

    def _affected_tests(self, paths: list[str]) -> Result:
        tests = sorted({p for p in self._affected(paths) if _is_test_path(p)})
        if not tests:
            raise _NoMatch("no affected tests")
        return Result(ResultStatus.OK, tuple(tests))

    def _change_impact(self, paths: list[str]) -> Result:
        if not paths:
            raise _NoMatch("no paths given")
        impacted = {self._norm(p) for p in paths} | set(self._affected(paths))
        return Result(ResultStatus.OK, Impact(tuple(sorted(impacted)), ()))

    def _empty_or_error(self, out: str) -> None:
        """結果0件。明示的な該当なし表現か空配列のときだけ NOT_FOUND にする。"""
        stripped = _strip_ansi(out).strip()
        if stripped == "[]" or _NOT_FOUND.search(stripped):
            raise _NoMatch("no matches")
        raise CodeIntelError("codegraph: 出力を解釈できません")

    def _load_json(self, out: str) -> Any:
        try:
            return json.loads(out)
        except json.JSONDecodeError as exc:
            if _NOT_FOUND.search(_strip_ansi(out)):
                raise _NoMatch("no matches") from exc
            raise CodeIntelError("codegraph: JSON を解釈できません") from exc

    def _norm(self, raw: str) -> str:
        path = Path(raw)
        if path.is_absolute():
            try:
                path = path.relative_to(self._root)
            except ValueError:
                return PurePosixPath(path.as_posix()).as_posix()
        return os.path.normpath(path.as_posix()).replace(os.sep, "/")


def _text_entries(out: str) -> list[tuple[str, str, str, int]]:
    """`kind  name` の次行が `  path:line` の組を (kind, name, path, line) で返す。"""
    lines = [ln for ln in _strip_ansi(out).splitlines() if ln.strip()]
    entries: list[tuple[str, str, str, int]] = []
    for head, loc in zip(lines, lines[1:], strict=False):
        entry = _TEXT_ENTRY.match(head) if not head.startswith(" ") else None
        location = _TEXT_LOCATION.match(loc)
        if entry and location:
            entries.append(
                (entry.group(1), entry.group(2).strip(), location.group(1), int(location.group(2)))
            )
    return entries


def create_provider(root: Path) -> CodeGraphProvider:
    return CodeGraphProvider(root)
