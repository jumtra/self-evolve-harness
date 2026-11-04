"""Graphify CLI(Graphify-Labs/graphify, ADR-0004) を CodeIntelligenceProvider へ写像する。"""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from seh.contracts.common import Result, ResultStatus
from seh.contracts.module import HealthResult
from seh.providers.codeintel.base import Impact, Symbol
from seh.runtime.process import DEFAULT_ENV_ALLOWLIST, ProcessResult, build_env, run_process

NOT_INSTALLED_MESSAGE = (
    "graphify 未導入。導入は `uv tool install graphifyy`"
    "（提供元 Graphify-Labs/graphify を確認のうえ、LICENSE を確認）。"
    "seh は自動インストールしません"
)
_GRAPH_PATH = Path("graphify-out") / "graph.json"
_SUPPORTED_SCHEMA = ("1", 1)
_NODE_FILE_KEYS = ("file", "source_file", "path")
_EDGE_LIST_KEYS = ("edges", "links")
_SYMBOL_LINE = re.compile(r"^(?P<name>\S+) \((?P<kind>\w+)\) (?P<path>.+):(?P<line>\d+)$")


class GraphifyProvider:
    name = "graphify"

    def __init__(
        self, root: Path, *, command: str = "graphify", timeout_seconds: float = 300
    ) -> None:
        self._root = root
        self._command = command
        self._timeout = timeout_seconds

    def index(self, root: Path) -> Result:
        if shutil.which(self._command) is None:
            return Result(ResultStatus.ERROR, message=NOT_INSTALLED_MESSAGE)
        args = [".", "--update", "--no-viz"] if self._graph_file().exists() else [".", "--no-viz"]
        proc = self._run(args)
        if proc.exit_code != 0:
            return _failure(proc)
        return Result(ResultStatus.OK)

    def search_symbols(self, query: str) -> Result:
        proc, early = self._query("query", query)
        if early is not None or proc is None:
            return early or Result(ResultStatus.ERROR)
        symbols = _parse_symbols(_text(proc))
        if not symbols:
            return Result(ResultStatus.ERROR, message="graphify query の出力を解析できません")
        return Result(ResultStatus.OK, symbols)

    def dependencies(self, symbol: str) -> Result:
        proc, early = self._query("explain", symbol)
        if early is not None or proc is None:
            return early or Result(ResultStatus.ERROR)
        files = _parse_files(_text(proc))
        if not files:
            return Result(ResultStatus.ERROR, message="graphify explain の出力を解析できません")
        return Result(ResultStatus.OK, files)

    def change_impact(self, paths: list[str]) -> Result:
        graph_file = self._graph_file()
        if not graph_file.is_file():
            return Result(ResultStatus.ERROR, message="INDEX_MISSING: graphify-out/graph.json")
        try:
            graph = json.loads(graph_file.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            return Result(ResultStatus.ERROR, message=f"graph.json を読めません: {exc}")
        if not isinstance(graph, dict) or graph.get("schema_version") not in _SUPPORTED_SCHEMA:
            version = graph.get("schema_version") if isinstance(graph, dict) else None
            return Result(
                ResultStatus.ERROR,
                message=f"UNSUPPORTED_GRAPH_SCHEMA: schema_version={version!r}",
            )
        files_by_id = _node_files(graph.get("nodes"))
        edges = _edges(graph)
        if files_by_id is None or edges is None:
            return Result(ResultStatus.ERROR, message="graph.json のノード/エッジ形式が未知です")
        changed = set(paths)
        sources = {nid for nid, file in files_by_id.items() if file in changed}
        impacted = set(changed)
        for src, dst in edges:
            for here, there in ((src, dst), (dst, src)):
                if here in sources and there in files_by_id:
                    impacted.add(files_by_id[there])
        return Result(ResultStatus.OK, Impact(tuple(sorted(impacted)), ()))

    def affected_tests(self, paths: list[str]) -> Result:
        return Result(
            ResultStatus.UNSUPPORTED, message="Graphify に対応する CLI が無いため未対応 (ADR-0004)"
        )

    def healthcheck(self) -> Result:
        if shutil.which(self._command) is None:
            return Result(
                ResultStatus.ERROR,
                HealthResult(ok=False, message=NOT_INSTALLED_MESSAGE),
                message=NOT_INSTALLED_MESSAGE,
            )
        proc = self._run(["--version"])
        ok = proc.exit_code == 0 and not proc.timed_out
        message = _text(proc).strip() or f"exit {proc.exit_code}"
        return Result(
            ResultStatus.OK if ok else ResultStatus.ERROR,
            HealthResult(ok=ok, message=message),
            message=message,
        )

    def _graph_file(self) -> Path:
        return self._root / _GRAPH_PATH

    def _query(self, sub: str, arg: str) -> tuple[ProcessResult | None, Result | None]:
        """(proc, None)=回答あり / (None, Result)=呼出し側がそのまま返す結果。"""
        if shutil.which(self._command) is None:
            return None, Result(ResultStatus.ERROR, message=NOT_INSTALLED_MESSAGE)
        proc = self._run([sub, arg])
        if proc.exit_code == 0:
            return proc, None
        if proc.exit_code == 4:
            return None, Result(ResultStatus.NOT_FOUND, message=f"not found: {arg}")
        if proc.exit_code == 3:
            return None, Result(ResultStatus.ERROR, message=f"AMBIGUOUS: {_text(proc).strip()}")
        return None, _failure(proc)

    def _run(self, args: list[str]) -> ProcessResult:
        # LLM 経由の抽出を止め、コード解析だけを行わせる
        env = build_env(DEFAULT_ENV_ALLOWLIST, os.environ, {"GRAPHIFY_BACKEND": "none"})
        argv = [self._command, *args]
        with ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(
                asyncio.run,
                run_process(argv, cwd=self._root, env=env, timeout_seconds=self._timeout),
            ).result()


def _text(proc: ProcessResult) -> str:
    return proc.stdout.decode("utf-8", errors="replace")


def _failure(proc: ProcessResult) -> Result:
    if proc.timed_out:
        return Result(ResultStatus.ERROR, message="graphify timed out")
    detail = proc.stderr.decode("utf-8", errors="replace").strip()
    return Result(ResultStatus.ERROR, message=f"graphify exit {proc.exit_code}: {detail}")


def _parse_symbols(text: str) -> tuple[Symbol, ...]:
    try:
        data = json.loads(text)
    except ValueError:
        data = None
    if isinstance(data, dict):
        data = data.get("symbols")
    if isinstance(data, list):
        return _symbols_from_json(data)
    symbols = []
    for line in text.splitlines():
        match = _SYMBOL_LINE.match(line.strip())
        if match is None:
            continue
        symbols.append(Symbol(match["name"], match["kind"], match["path"], int(match["line"])))
    return tuple(symbols)


def _symbols_from_json(items: list[object]) -> tuple[Symbol, ...]:
    symbols = []
    for item in items:
        if not isinstance(item, dict):
            return ()
        name, path, line = item.get("name"), item.get("path"), item.get("line")
        if not isinstance(name, str) or not isinstance(path, str) or not isinstance(line, int):
            return ()
        symbols.append(Symbol(name, str(item.get("kind", "unknown")), path, line))
    return tuple(symbols)


def _parse_files(text: str) -> tuple[str, ...]:
    try:
        data = json.loads(text)
    except ValueError:
        data = None
    if isinstance(data, dict):
        data = data.get("files")
    if isinstance(data, list):
        return tuple(f for f in data if isinstance(f, str)) if data else ()
    files = [ln.strip()[2:].strip() for ln in text.splitlines() if ln.strip()[:2] in ("- ", "* ")]
    return tuple(f for f in files if f)


def _node_files(nodes: object) -> dict[str, str] | None:
    if not isinstance(nodes, list):
        return None
    files: dict[str, str] = {}
    for node in nodes:
        if not isinstance(node, dict) or "id" not in node:
            continue
        file = next((node[k] for k in _NODE_FILE_KEYS if isinstance(node.get(k), str)), None)
        if file is not None:
            files[str(node["id"])] = file
    return files or None


def _edges(graph: dict[str, object]) -> list[tuple[str, str]] | None:
    raw = next((graph[k] for k in _EDGE_LIST_KEYS if isinstance(graph.get(k), list)), None)
    if not isinstance(raw, list):
        return None
    return [
        (str(e["source"]), str(e["target"]))
        for e in raw
        if isinstance(e, dict) and "source" in e and "target" in e
    ]


def create_provider(root: Path) -> GraphifyProvider:
    return GraphifyProvider(root)
