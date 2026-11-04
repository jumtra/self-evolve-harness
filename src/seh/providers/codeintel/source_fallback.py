"""外部ツール不要の Code Intelligence。解析不能は結果ゼロにせず UNSUPPORTED を返す。"""

from __future__ import annotations

import ast
import asyncio
import json
import os
import re
import shutil
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from seh.contracts.common import Result, ResultStatus
from seh.contracts.module import HealthResult
from seh.providers.codeintel.base import Impact, Symbol
from seh.runtime.process import build_env, run_process

EXCLUDED_DIRS = frozenset({".git", ".venv", "node_modules", "dist", "build", ".harness"})
_KEYWORDS = "def|class|function|func|fn|interface|struct|type"
_KIND = {
    "def": "function",
    "function": "function",
    "func": "function",
    "fn": "function",
    "class": "class",
    "interface": "class",
    "struct": "class",
    "type": "class",
}
_MAX_BYTES = 1_000_000
_RG_TIMEOUT = 30.0
_DEF_RE = re.compile(rf"\b({_KEYWORDS})\s+(\w+)")


class SourceFallbackProvider:
    name = "none"

    def __init__(self, root: Path) -> None:
        self._root = root

    def index(self, root: Path) -> Result:
        return Result(ResultStatus.OK)

    def search_symbols(self, query: str) -> Result:
        symbols = [*self._python_symbols(query), *self._other_symbols(query)]
        if not symbols:
            return Result(ResultStatus.NOT_FOUND, message=f"symbol not found: {query}")
        symbols.sort(key=lambda s: (s.path, s.line, s.name))
        return Result(ResultStatus.OK, tuple(symbols))

    def dependencies(self, symbol: str) -> Result:
        defined = {s.path for s in self._all_definitions(symbol)}
        referencing = self._referencing_files(symbol) - defined
        if not referencing:
            return Result(ResultStatus.NOT_FOUND, message=f"no references: {symbol}")
        return Result(ResultStatus.OK, tuple(sorted(referencing)))

    def change_impact(self, paths: list[str]) -> Result:
        changed: set[str] = set()
        for raw in paths:
            rel = self._relative(raw)
            if rel is None:
                return Result(ResultStatus.ERROR, message=f"path outside root: {raw}")
            changed.add(rel)
        if not changed:
            return Result(ResultStatus.NOT_FOUND, message="no paths given")
        names = {name for rel in changed for name in self._top_level_names(rel)}
        impacted = set(changed)
        for name in names:
            impacted |= self._referencing_files(name)
        return Result(ResultStatus.OK, Impact(tuple(sorted(impacted)), tuple(sorted(names))))

    def affected_tests(self, paths: list[str]) -> Result:
        return Result(
            ResultStatus.UNSUPPORTED,
            message="正確に求められないため未対応（名前規則での推定はしない）",
        )

    def healthcheck(self) -> Result:
        rg = "available" if shutil.which("rg") else "missing (python re scan)"
        return Result(
            ResultStatus.OK,
            HealthResult(ok=True, message=f"source fallback ready; rg: {rg}"),
            message=f"source fallback ready; rg: {rg}",
        )

    def _files(self, suffix_py: bool | None = None) -> Iterator[Path]:
        """suffix_py: True=Python のみ / False=Python 以外 / None=全て。"""
        for dirpath, dirnames, filenames in os.walk(self._root):
            dirnames[:] = sorted(d for d in dirnames if d not in EXCLUDED_DIRS)
            for filename in sorted(filenames):
                path = Path(dirpath) / filename
                if suffix_py is not None and (path.suffix == ".py") != suffix_py:
                    continue
                yield path

    def _read(self, path: Path) -> str | None:
        try:
            if path.stat().st_size > _MAX_BYTES:
                return None
            return path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return None

    def _rel(self, path: Path) -> str:
        return path.relative_to(self._root).as_posix()

    def _relative(self, raw: str) -> str | None:
        resolved = (self._root / raw).resolve()
        try:
            return resolved.relative_to(self._root.resolve()).as_posix()
        except ValueError:
            return None

    def _python_symbols(self, query: str | None) -> list[Symbol]:
        found: list[Symbol] = []
        for path in self._files(True):
            source = self._read(path)
            if source is None:
                continue
            try:
                tree = ast.parse(source)
            except SyntaxError:
                continue
            rel = self._rel(path)
            for node, kind in _walk_definitions(tree):
                if query is None or node.name == query:
                    found.append(Symbol(node.name, kind, rel, node.lineno))
        return found

    def _other_symbols(self, query: str) -> list[Symbol]:
        pattern = re.compile(rf"\b({_KEYWORDS})\s+{re.escape(query)}\b")
        hits = self._rg_hits(pattern) if shutil.which("rg") else None
        if hits is None:
            hits = self._scan_hits(pattern)
        found: list[Symbol] = []
        for rel, line_no, text in hits:
            match = pattern.search(text)
            if match:
                found.append(Symbol(query, _KIND[match.group(1)], rel, line_no))
        return found

    def _scan_hits(self, pattern: re.Pattern[str]) -> list[tuple[str, int, str]]:
        hits: list[tuple[str, int, str]] = []
        for path in self._files(False):
            source = self._read(path)
            if source is None:
                continue
            for line_no, line in enumerate(source.splitlines(), start=1):
                if pattern.search(line):
                    hits.append((self._rel(path), line_no, line))
        return hits

    def _rg_hits(self, pattern: re.Pattern[str]) -> list[tuple[str, int, str]] | None:
        """rg の実行に失敗したら None を返し、呼び出し側が Python 走査へ切り替える。"""
        argv = ["rg", "--json", "-n", "--no-ignore", "--hidden", "-g", "!*.py"]
        for name in sorted(EXCLUDED_DIRS):
            argv += ["-g", f"!{name}"]
        argv += ["-e", pattern.pattern, "."]
        env = build_env(("PATH", "HOME", "LANG", "LC_ALL"), os.environ)
        try:
            with ThreadPoolExecutor(max_workers=1) as pool:
                proc = pool.submit(
                    asyncio.run,
                    run_process(argv, cwd=self._root, env=env, timeout_seconds=_RG_TIMEOUT),
                ).result()
        except OSError:
            return None
        if proc.timed_out or proc.stdout_truncated or proc.exit_code not in (0, 1):
            return None
        hits: list[tuple[str, int, str]] = []
        for raw in proc.stdout.decode("utf-8", errors="replace").splitlines():
            event = json.loads(raw)
            if event.get("type") != "match":
                continue
            data = event["data"]
            rel = Path(data["path"]["text"]).as_posix().removeprefix("./")
            hits.append((rel, data["line_number"], data["lines"].get("text", "")))
        return hits

    def _all_definitions(self, name: str) -> list[Symbol]:
        return [*self._python_symbols(name), *self._other_symbols(name)]

    def _top_level_names(self, rel: str) -> set[str]:
        path = self._root / rel
        source = self._read(path) if path.is_file() else None
        if source is None:
            return set()
        if path.suffix != ".py":
            return {m.group(2) for m in _DEF_RE.finditer(source)}
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return set()
        return {
            node.name
            for node in tree.body
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef)
        }

    def _referencing_files(self, name: str) -> set[str]:
        word = re.compile(rf"\b{re.escape(name)}\b")
        result: set[str] = set()
        for path in self._files():
            source = self._read(path)
            if source is not None and word.search(source):
                result.add(self._rel(path))
        return result


def _walk_definitions(
    tree: ast.AST, in_class: bool = False
) -> Iterator[tuple[ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef, str]]:
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.ClassDef):
            yield node, "class"
            yield from _walk_definitions(node, True)
        elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            yield node, "method" if in_class else "function"
            yield from _walk_definitions(node, False)
        else:
            yield from _walk_definitions(node, in_class)
