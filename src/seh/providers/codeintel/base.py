"""Code Intelligence の共通契約。上位は Result.data の形だけに依存する。"""

from __future__ import annotations

import importlib
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from seh.contracts.common import Result, ResultStatus
from seh.contracts.module import CodeIntelligenceProvider

_OPS = frozenset({"index", "search_symbols", "dependencies", "change_impact", "affected_tests"})
# 後続タスク(T52/T53)が提供する module。`create_provider(root)` を公開する前提
_OPTIONAL_PROVIDERS = {
    "codegraph": "seh.providers.codeintel.codegraph",
    "graphify": "seh.providers.codeintel.graphify",
}


@dataclass(frozen=True)
class Symbol:
    name: str
    kind: str  # function | class | method | variable | unknown
    path: str
    line: int


@dataclass(frozen=True)
class Impact:
    paths: tuple[str, ...]
    symbols: tuple[str, ...]


class CodeIntelError(Exception):
    pass


def resolve_with_fallback(
    primary: CodeIntelligenceProvider,
    fallback: CodeIntelligenceProvider | None,
    op: str,
    *args: object,
    mode: Literal["source", "stop"],
) -> Result:
    """UNSUPPORTED のときだけ fallback する。ERROR は障害を隠さないためそのまま返す。"""
    if op not in _OPS:
        raise CodeIntelError(f"unknown operation: {op}")
    result: Result = getattr(primary, op)(*args)
    if result.status is not ResultStatus.UNSUPPORTED or mode == "stop" or fallback is None:
        return result
    fallback_result: Result = getattr(fallback, op)(*args)
    label = f"fallback:{getattr(fallback, 'name', type(fallback).__name__)}"
    message = f"{label} {fallback_result.message}" if fallback_result.message else label
    return Result(fallback_result.status, fallback_result.data, fallback_result.evidence, message)


def provider_for(name: str, root: Path) -> CodeIntelligenceProvider:
    if name == "none":
        from seh.providers.codeintel.source_fallback import SourceFallbackProvider

        return SourceFallbackProvider(root)
    module_name = _OPTIONAL_PROVIDERS.get(name)
    if module_name is None:
        raise CodeIntelError(f"unknown provider: {name}")
    try:
        module = importlib.import_module(module_name)
    except ModuleNotFoundError as exc:
        if exc.name != module_name:
            raise
        raise CodeIntelError("provider not available") from exc
    return module.create_provider(root)
