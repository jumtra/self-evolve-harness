from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

__all__ = [
    "GENERATED_TARGETS",
    "InventoryEntry",
    "KnownPath",
    "detect_v1",
    "fingerprint",
    "load_known_paths",
    "take_inventory",
]

_KNOWN_PATHS_FILE = Path(__file__).with_name("v1_known_paths.json")
# ホスト生成先。v1 既知パス外でも既存物があれば USER_OWNED_CONFLICT として列挙する（D12）
GENERATED_TARGETS = (
    ".agents/skills",
    ".agents/rules",
    ".agents/hooks.json",
    ".agents/agents",
    ".opencode",
    ".codex",
)
# 計画に載せるが v2 が書き換えないもの
_PASSTHROUGH = (".agents/skills.json", ".claude/settings.local.json")
_V1_KINDS = frozenset({"skill", "agent", "rule"})


@dataclass(frozen=True)
class KnownPath:
    kind: str
    v2_action: str
    sha256: str


@dataclass(frozen=True)
class InventoryEntry:
    path: str
    exists: bool
    is_symlink: bool
    link_target: str | None
    sha256: str | None
    known: KnownPath | None


def load_known_paths() -> tuple[str, dict[str, KnownPath]]:
    data = json.loads(_KNOWN_PATHS_FILE.read_text(encoding="utf-8"))
    paths = {
        rel: KnownPath(kind=v["kind"], v2_action=v["v2_action"], sha256=v["sha256"])
        for rel, v in data["paths"].items()
    }
    return data["baseline_ref"], paths


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _tree_digest(directory: Path) -> str:
    lines: list[str] = []
    for current, dirnames, filenames in os.walk(directory, followlinks=False):
        base = Path(current)
        for name in sorted(dirnames + filenames):
            child = base / name
            rel = child.relative_to(directory).as_posix()
            if child.is_symlink():
                lines.append(f"{rel}\tlink:{os.readlink(child)}")
            elif child.is_dir():
                lines.append(f"{rel}\tdir")
            else:
                lines.append(f"{rel}\tfile:{_file_sha256(child)}")
    return "tree:" + hashlib.sha256("\n".join(sorted(lines)).encode()).hexdigest()


def fingerprint(root: Path, rel: str) -> str | None:
    """現物の同一性。file=sha256 / link=symlink:<先> / dir=tree:<digest>。"""
    path = root / rel
    if path.is_symlink():
        return f"symlink:{os.readlink(path)}"
    if path.is_dir():
        return _tree_digest(path)
    if path.is_file():
        return _file_sha256(path)
    return None


def _symlink_ancestor(root: Path, rel: str) -> str | None:
    parts = PurePosixPath(rel).parts
    for depth in range(1, len(parts)):
        sub = PurePosixPath(*parts[:depth])
        if (root / sub).is_symlink():
            return str(sub)
    return None


def _entry(root: Path, rel: str, known: KnownPath | None) -> InventoryEntry:
    fp = fingerprint(root, rel)
    if fp is None:
        return InventoryEntry(rel, False, False, None, None, known)
    if fp.startswith("symlink:"):
        return InventoryEntry(rel, True, True, fp.removeprefix("symlink:"), None, known)
    return InventoryEntry(rel, True, False, None, fp, known)


def take_inventory(root: Path) -> list[InventoryEntry]:
    """read-only。リンク配下のパスは個別に列挙せず、リンク自体を1件として扱う。"""
    _, known = load_known_paths()
    candidates: dict[str, KnownPath | None] = dict(known)
    for rel in (*GENERATED_TARGETS, *_PASSTHROUGH):
        candidates.setdefault(rel, None)
    entries: dict[str, InventoryEntry] = {}
    for rel, info in candidates.items():
        ancestor = _symlink_ancestor(root, rel)
        if ancestor is None:
            entries.setdefault(rel, _entry(root, rel, info))
        else:
            entries.setdefault(ancestor, _entry(root, ancestor, candidates.get(ancestor)))
    # 生成先・パススルーは無ければ列挙しない。既知パスのみ exists=False で残す
    return [e for _, e in sorted(entries.items()) if e.exists or e.path in known]


def detect_v1(root: Path) -> bool:
    _, known = load_known_paths()
    return any(
        (root / rel).exists() or (root / rel).is_symlink()
        for rel, info in known.items()
        if info.kind in _V1_KINDS
    )
