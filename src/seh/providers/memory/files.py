"""v1 の `.agent-memory/` 形式をそのまま読み書きする File 実装。"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from seh.contracts.common import Result, ResultStatus
from seh.contracts.module import MemoryRecord
from seh.ownership import atomic_write
from seh.providers.memory.base import as_memory_type, reject_unsafe, slugify

INDEX_NAME = "MEMORY.md"
_ID = re.compile(r"^[a-z0-9_]+$")
_INDEX_HEADER = "# MEMORY 索引\n\n"
_DESC_MAX = 60
_LINE_MAX = 150
_PLAIN_UNSAFE = re.compile(r"(^[\s\"'#&*!|>%@`\[\]{}-])|(: )|( #)|(\s$)")


@dataclass
class _Doc:
    top: list[tuple[str, str | list[str]]] = field(default_factory=list)
    body: str = ""

    def scalar(self, key: str) -> str | None:
        for k, v in self.top:
            if k == key and isinstance(v, str):
                return _unquote(v)
        return None

    def meta_lines(self) -> list[str]:
        for k, v in self.top:
            if k == "metadata" and isinstance(v, list):
                return v
        return []


def _unquote(value: str) -> str:
    value = value.strip()
    if value.startswith('"') and value.endswith('"') and len(value) >= 2:
        try:
            loaded = json.loads(value)
        except ValueError:
            return value
        return loaded if isinstance(loaded, str) else value
    return value


def _quote(value: str) -> str:
    return json.dumps(value, ensure_ascii=False) if _PLAIN_UNSAFE.search(value) else value


def _kv(line: str) -> tuple[str, str] | None:
    key, sep, value = line.strip().partition(":")
    return (key.strip(), value.strip()) if sep and key.strip() else None


def _parse(text: str) -> _Doc | None:
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return None
    try:
        end = next(i for i in range(1, len(lines)) if lines[i].strip() == "---")
    except StopIteration:
        return None
    doc = _Doc(body="\n".join(lines[end + 1 :]))
    children: list[str] | None = None  # 直前のキーのインデント行の受け皿
    for line in lines[1:end]:
        if line[:1] in (" ", "\t") and children is not None:
            children.append(line)
            continue
        pair = _kv(line)
        if pair is None:
            children = None
            if line.strip():
                doc.top.append((line, []))
            continue
        key, value = pair
        if value:
            children = None
            doc.top.append((key, value))
        else:
            children = []
            doc.top.append((key, children))
    return doc


def _meta_dict(lines: list[str]) -> dict[str, object]:
    out: dict[str, object] = {}
    for line in lines:
        pair = _kv(line)
        if pair is None:
            continue
        key, raw = pair
        value = _unquote(raw)
        out[key] = int(value) if value.isdigit() else value
    return out


def _render_meta_value(value: object) -> str:
    return _quote(str(value)).replace("\n", " ")


class FileMemoryProvider:
    def __init__(self, root: Path, *, directory: str = ".agent-memory") -> None:
        self._dir = root / directory

    # -- API ---------------------------------------------------------------

    def save(self, record: MemoryRecord) -> Result:
        if (rejected := reject_unsafe(record)) is not None:
            return rejected
        record_id = self._resolve_id(record)
        path = self._dir / f"{record_id}.md"
        existing = _parse(path.read_text(encoding="utf-8")) if path.is_file() else None
        atomic_write(path, self._render(record, record_id, existing).encode("utf-8"))
        self._update_index(record_id, record.title)
        return Result(ResultStatus.OK, record_id)

    def get(self, record_id: str) -> Result:
        if not _ID.match(record_id):
            return Result(ResultStatus.ERROR, message=f"INVALID_ID: {record_id!r}")
        record = self._read(self._dir / f"{record_id}.md")
        if record is None:
            return Result(ResultStatus.NOT_FOUND, message=record_id)
        return Result(ResultStatus.OK, record)

    def delete(self, record_id: str) -> Result:
        if not _ID.match(record_id):
            return Result(ResultStatus.ERROR, message=f"INVALID_ID: {record_id!r}")
        path = self._dir / f"{record_id}.md"
        if not path.is_file():
            return Result(ResultStatus.NOT_FOUND, message=record_id)
        path.unlink()
        self._update_index(record_id, None)
        return Result(ResultStatus.OK)

    def list(self) -> Result:
        return Result(ResultStatus.OK, self._records())

    def search(self, query: str) -> Result:
        needle = query.lower()
        hits = [
            record
            for path, record in self._records_with_path()
            if needle in path.read_text(encoding="utf-8", errors="replace").lower()
        ]
        if not hits:
            return Result(ResultStatus.NOT_FOUND, message=query)
        return Result(ResultStatus.OK, hits)

    # -- internals ---------------------------------------------------------

    def _files(self) -> list[Path]:
        if not self._dir.is_dir():
            return []
        return sorted(p for p in self._dir.glob("*.md") if p.name != INDEX_NAME)

    def _records_with_path(self) -> list[tuple[Path, MemoryRecord]]:
        pairs = []
        for path in self._files():
            record = self._read(path)
            if record is not None:
                pairs.append((path, record))
        return pairs

    def _records(self) -> list[MemoryRecord]:
        return [r for _, r in self._records_with_path()]

    def _read(self, path: Path) -> MemoryRecord | None:
        if not path.is_file():
            return None
        doc = _parse(path.read_text(encoding="utf-8", errors="replace"))
        if doc is None:
            return None
        meta = _meta_dict(doc.meta_lines())
        stem = path.stem
        kind = as_memory_type(str(meta.pop("type", stem.split("_", 1)[0])))
        if kind is None:
            return None
        title = doc.scalar("description") or doc.scalar("name") or stem
        return MemoryRecord(
            id=stem,
            type=kind,
            title=title,
            body=doc.body.lstrip("\n"),
            metadata=meta,
        )

    def _resolve_id(self, record: MemoryRecord) -> str:
        prefix = f"{record.type}_"
        if (
            _ID.match(record.id)
            and record.id.startswith(prefix)
            and (self._dir / f"{record.id}.md").is_file()
        ):
            return record.id
        for existing in self._records():
            if existing.type == record.type and existing.title == record.title:
                return existing.id
        if _ID.match(record.id) and record.id.startswith(prefix):
            return record.id
        return prefix + slugify(record.title)

    def _render(self, record: MemoryRecord, record_id: str, existing: _Doc | None) -> str:
        name = (existing.scalar("name") if existing else None) or record_id.split("_", 1)[-1]
        old_meta = existing.meta_lines() if existing else []
        new_meta = {"type": record.type, **{str(k): v for k, v in record.metadata.items()}}
        meta_lines: list[str] = []
        done: set[str] = set()
        for line in old_meta:
            pair = _kv(line)
            if pair is not None and pair[0] in new_meta:
                meta_lines.append(f"  {pair[0]}: {_render_meta_value(new_meta[pair[0]])}")
                done.add(pair[0])
            else:
                meta_lines.append(line)
        for key, value in new_meta.items():
            if key not in done:
                meta_lines.append(f"  {key}: {_render_meta_value(value)}")
        out = ["---", f"name: {_quote(name)}", f"description: {_quote(record.title)}", "metadata:"]
        out += meta_lines
        for key, value in existing.top if existing else []:
            if key in ("name", "description", "metadata"):
                continue
            if isinstance(value, str):
                out.append(f"{key}: {value}")
            else:
                out += [f"{key}:", *value]
        out.append("---")
        body = record.body if record.body.endswith("\n") else record.body + "\n"
        return "\n".join(out) + "\n" + body

    def _update_index(self, record_id: str, title: str | None) -> None:
        index = self._dir / INDEX_NAME
        text = index.read_text(encoding="utf-8") if index.is_file() else _INDEX_HEADER
        marker = f"]({record_id}.md)"
        lines = text.split("\n")
        kept = [ln for ln in lines if not (ln.startswith("- [") and marker in ln)]
        position = next(
            (i for i, ln in enumerate(lines) if ln.startswith("- [") and marker in ln), None
        )
        if title is not None:
            entry = f"- [{title}]({record_id}.md) — {title[:_DESC_MAX]}"[:_LINE_MAX]
            if position is not None:
                kept.insert(position, entry)
            else:
                while kept and kept[-1] == "":
                    kept.pop()
                kept += [entry, ""]
        elif not index.is_file():
            return
        atomic_write(index, "\n".join(kept).encode("utf-8"))
