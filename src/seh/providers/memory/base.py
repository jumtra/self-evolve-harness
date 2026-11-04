"""Memory Provider 共通: 検証・slug・秘密検査・provider 切替。"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Literal, Protocol

from seh.config import MemoryConfig
from seh.contracts.common import Result, ResultStatus
from seh.contracts.module import MemoryProvider, MemoryRecord
from seh.redaction import contains_secret

MemoryType = Literal["user", "feedback", "project", "reference"]
MEMORY_TYPES: tuple[MemoryType, ...] = ("user", "feedback", "project", "reference")
_NON_SLUG = re.compile(r"[^a-z0-9]+")


class MemoryError(Exception):
    pass


def as_memory_type(value: str) -> MemoryType | None:
    for kind in MEMORY_TYPES:
        if kind == value:
            return kind
    return None


class HasMemoryConfig(Protocol):
    @property
    def memory(self) -> MemoryConfig: ...


def slugify(title: str) -> str:
    slug = _NON_SLUG.sub("_", title.lower()).strip("_")
    if slug:
        return slug
    return hashlib.sha1(title.encode("utf-8")).hexdigest()[:8]


def validate_record(record: MemoryRecord) -> None:
    if record.type not in MEMORY_TYPES:
        raise ValueError(f"unknown memory type: {record.type!r}")
    if not record.title.strip():
        raise ValueError("title must not be empty")
    if "\n" in record.title or "\r" in record.title:
        raise ValueError("title must be a single line")


def reject_unsafe(record: MemoryRecord) -> Result | None:
    """保存してはならないレコードなら理由付き ERROR を返す。"""
    try:
        validate_record(record)
    except ValueError as exc:
        return Result(ResultStatus.ERROR, message=f"INVALID_RECORD: {exc}")
    texts = [record.title, record.body, *(str(v) for v in record.metadata.values())]
    if any(contains_secret(t) for t in texts):
        return Result(
            ResultStatus.ERROR,
            message="SECRET_IN_MEMORY: 秘密情報を含む記憶は保存しません",
        )
    return None


def memory_provider_for(config: HasMemoryConfig, root: Path) -> MemoryProvider:
    """config.memory.provider / path で File と Engram を切り替える。"""
    from seh.providers.memory.engram import EngramMemoryProvider
    from seh.providers.memory.files import FileMemoryProvider

    memory = config.memory
    if memory.provider == "engram":
        return EngramMemoryProvider(project=root.name)
    if memory.provider == "file":
        return FileMemoryProvider(root, directory=memory.path)
    raise MemoryError(f"unknown memory provider: {memory.provider!r}")
