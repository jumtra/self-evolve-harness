"""ドメイン知識（domain.md）の生成・部分取得と verified constraints の保存。

domain.md は常時 Context に載せない。呼出側は read_section / search_domain / constraints_for で
必要な分だけ取り出す（FR-039, P7-04）。
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from seh.contracts.common import ResultStatus
from seh.contracts.module import CodeIntelligenceProvider
from seh.globs import match_path
from seh.init.detect import IGNORED_DIRS, DetectionResult
from seh.ownership import atomic_write
from seh.providers.codeintel.base import Symbol
from seh.redaction import contains_secret

_BANNER = "<!-- 常時読込しない。seh の knowledge API で必要な節だけ取得する -->"
_UNFILLED = "（未記入）"
_MAX_SYMBOLS = 20
_KNOWLEDGE_DIR = Path(".harness") / "knowledge"
_DOMAIN = _KNOWLEDGE_DIR / "domain.md"
_CONSTRAINTS = _KNOWLEDGE_DIR / "verified_constraints.jsonl"


# --- domain.md ------------------------------------------------------------------------------


def _top_dirs(root: Path) -> list[str]:
    found: list[str] = []

    def visible(p: Path) -> bool:
        return (
            p.is_dir()
            and not p.name.startswith(".")
            and p.name not in IGNORED_DIRS | {"__pycache__"}
        )

    for first in sorted(p for p in root.iterdir() if visible(p)):
        found.append(first.name)
        found += [f"{first.name}/{c.name}" for c in sorted(first.iterdir()) if visible(c)]
    return found


def _overview(detection: DetectionResult) -> list[str]:
    if not detection.root_apps:
        return [f"- アプリ: {_UNFILLED}"]
    lines: list[str] = []
    for app in detection.root_apps:
        langs = ", ".join(app.languages)
        lines.append(f"- {app.path}: 言語={langs} / パッケージマネージャ={app.package_manager}")
    return lines


def _symbol_lines(code_intel: CodeIntelligenceProvider) -> list[str]:
    result = code_intel.search_symbols("")
    if result.status is not ResultStatus.OK or not isinstance(result.data, tuple):
        return [f"取得できませんでした（{result.status.value}）"]
    symbols = [s for s in result.data if isinstance(s, Symbol)][:_MAX_SYMBOLS]
    return [f"- {s.name} ({s.kind}) {s.path}:{s.line}" for s in symbols]


def generate_domain_md(
    root: Path,
    detection: DetectionResult,
    *,
    code_intel: CodeIntelligenceProvider | None = None,
) -> str:
    lines = [_BANNER, "", "# ドメイン知識", "", "## プロジェクト概要", "", *_overview(detection)]
    lines += ["", "## ディレクトリの使い分け", "", "| ディレクトリ | 役割 |", "| --- | --- |"]
    lines += [f"| {d} | {_UNFILLED} |" for d in _top_dirs(root)]
    if code_intel is not None:
        lines += ["", "## 主要シンボル", "", *_symbol_lines(code_intel)]
    for heading in ("主要概念", "データフロー", "Gotchas"):
        lines += ["", f"## {heading}", "", _UNFILLED]
    return "\n".join(lines) + "\n"


def sections(text: str) -> list[str]:
    return [line for line in text.splitlines() if line.startswith("## ")]


def _split_sections(text: str) -> list[tuple[str, str]]:
    """(見出し名, 見出し行を含む節本文)。"""
    out: list[tuple[str, list[str]]] = []
    for line in text.splitlines():
        if line.startswith("## "):
            out.append((line[3:].strip(), [line]))
        elif out:
            out[-1][1].append(line)
    return [(name, "\n".join(body).rstrip() + "\n") for name, body in out]


def _read_domain(root: Path) -> str | None:
    path = root / _DOMAIN
    return path.read_text(encoding="utf-8") if path.is_file() else None


def read_section(root: Path, heading: str) -> str | None:
    text = _read_domain(root)
    if text is None:
        return None
    wanted = heading.removeprefix("## ").strip()
    return next((body for name, body in _split_sections(text) if name == wanted), None)


def search_domain(root: Path, query: str, *, max_chars: int = 2000) -> list[tuple[str, str]]:
    text = _read_domain(root)
    if text is None:
        return []
    needle = query.lower()
    hits: list[tuple[str, str]] = []
    remaining = max_chars
    for name, body in _split_sections(text):
        if remaining <= 0:
            break
        if needle not in body.lower():
            continue
        excerpt = body[:remaining]
        hits.append((name, excerpt))
        remaining -= len(excerpt)
    return hits


# --- verified constraints -------------------------------------------------------------------


@dataclass(frozen=True)
class VerifiedConstraint:
    id: str
    statement: str
    scope_globs: tuple[str, ...]
    source_record: str
    evidence_refs: tuple[str, ...]
    created_at: str
    expires_at: str | None
    status: Literal["active", "retired"]


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _from_row(row: object) -> VerifiedConstraint:
    if not isinstance(row, dict):
        raise ValueError("constraint row must be an object")
    try:
        status = row["status"]
        if status not in ("active", "retired"):
            raise ValueError(f"invalid status: {status!r}")
        return VerifiedConstraint(
            id=str(row["id"]),
            statement=str(row["statement"]),
            scope_globs=tuple(row["scope_globs"]),
            source_record=str(row["source_record"]),
            evidence_refs=tuple(row["evidence_refs"]),
            created_at=str(row["created_at"]),
            expires_at=None if row["expires_at"] is None else str(row["expires_at"]),
            status=status,
        )
    except (KeyError, TypeError) as exc:
        raise ValueError(f"invalid constraint row: {exc!r}") from exc


def _read_rows(root: Path) -> list[dict[str, object]]:
    path = root / _CONSTRAINTS
    if not path.is_file():
        return []
    lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    rows: list[dict[str, object]] = []
    for index, line in enumerate(lines):
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            if index == len(lines) - 1:
                break  # 追記途中でクラッシュした最終行は無視する
            raise ValueError(f"invalid JSON at line {index + 1}") from exc
        _from_row(row)
        rows.append(row)
    return rows


def append_constraint(root: Path, c: VerifiedConstraint) -> None:
    if contains_secret(c.statement):
        raise ValueError("statement contains a secret")
    if any(row["id"] == c.id for row in _read_rows(root)):
        raise ValueError(f"duplicate constraint id: {c.id}")
    path = root / _CONSTRAINTS
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(asdict(c), ensure_ascii=False) + "\n")
        f.flush()


def load_constraints(
    root: Path, *, include_retired: bool = False, now: datetime
) -> list[VerifiedConstraint]:
    found = [_from_row(row) for row in _read_rows(root)]
    return [
        c
        for c in found
        if (include_retired or c.status == "active")
        and (c.expires_at is None or _parse_time(c.expires_at) > now)
    ]


def constraints_for(
    root: Path,
    paths: Sequence[str],
    *,
    now: datetime,
    max_items: int = 10,
    max_chars: int = 1500,
) -> list[VerifiedConstraint]:
    candidates = sorted(
        (
            c
            for c in load_constraints(root, now=now)
            if any(match_path(p, g) for p in paths for g in c.scope_globs)
        ),
        key=lambda c: _parse_time(c.created_at),
        reverse=True,
    )
    picked: list[VerifiedConstraint] = []
    used = 0
    for c in candidates:
        if len(picked) >= max_items or used + len(c.statement) > max_chars:
            break
        picked.append(c)
        used += len(c.statement)
    return picked


def retire_constraint(root: Path, id: str, *, reason: str) -> None:
    rows = _read_rows(root)
    if not any(row["id"] == id for row in rows):
        raise ValueError(f"unknown constraint id: {id}")
    updated = [
        {**row, "status": "retired", "retired_reason": reason} if row["id"] == id else row
        for row in rows
    ]
    body = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in updated)
    atomic_write(root / _CONSTRAINTS, body.encode("utf-8"))
