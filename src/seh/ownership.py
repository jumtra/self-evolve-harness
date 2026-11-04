from __future__ import annotations

import contextlib
import difflib
import hashlib
import json
import os
import secrets
import tempfile
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path, PurePosixPath
from types import TracebackType
from typing import Any

from seh.contracts import PlannedChange

__all__ = [
    "FileStatus",
    "ManifestEntry",
    "OwnershipManifest",
    "SymlinkConflict",
    "ThreeWayDiff",
    "Transaction",
    "atomic_write",
    "classify_change",
    "recover_incomplete",
    "render_three_way",
    "rollback",
]

MANIFEST_PATH = Path(".harness") / "ownership.json"
_DEFAULT_SNAPSHOT_DIR = Path(".harness") / "backups"
_DEFAULT_FILE_MODE = 0o644


class SymlinkConflict(Exception):
    """シンボリックリンク経由で別の実体へ書き込もうとした。"""


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _fsync_dir(directory: Path) -> None:
    fd = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def atomic_write(path: Path, data: bytes, *, mode: int | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if mode is None:
        mode = path.stat().st_mode & 0o777 if path.is_file() else _DEFAULT_FILE_MODE
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp_name, mode)
        os.replace(tmp_name, path)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp_name)
        raise
    _fsync_dir(path.parent)


def _atomic_symlink(path: Path, target: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.parent / f".{path.name}.{secrets.token_hex(4)}.tmp"
    os.symlink(target, tmp)
    try:
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp)
        raise
    _fsync_dir(path.parent)


# --- manifest -------------------------------------------------------------


@dataclass(frozen=True)
class ManifestEntry:
    sha256: str
    owner: str
    generator: str
    seh_version: str
    kind: str = "file"
    link_target: str | None = None


class OwnershipManifest:
    def __init__(self, files: dict[str, ManifestEntry] | None = None) -> None:
        self._files: dict[str, ManifestEntry] = files or {}

    @classmethod
    def load(cls, root: Path) -> OwnershipManifest:
        path = root / MANIFEST_PATH
        if not path.is_file():
            return cls()
        raw = json.loads(path.read_text(encoding="utf-8"))
        return cls({key: ManifestEntry(**value) for key, value in raw["files"].items()})

    def get(self, path: str) -> ManifestEntry | None:
        return self._files.get(path)

    def record(
        self,
        path: str,
        sha256: str,
        generator: str,
        seh_version: str,
        kind: str = "file",
        link_target: str | None = None,
    ) -> None:
        self._files[path] = ManifestEntry(
            sha256=sha256,
            owner="seh",
            generator=generator,
            seh_version=seh_version,
            kind=kind,
            link_target=link_target,
        )

    def forget(self, path: str) -> None:
        self._files.pop(path, None)

    def save(self, root: Path) -> None:
        files: dict[str, dict[str, Any]] = {}
        for key, entry in self._files.items():
            record = asdict(entry)
            if record["link_target"] is None:
                del record["link_target"]
            files[key] = record
        document = {"schema_version": 1, "files": files}
        text = json.dumps(document, indent=2, sort_keys=True) + "\n"
        atomic_write(root / MANIFEST_PATH, text.encode("utf-8"))


# --- path validation --------------------------------------------------------


def _check_path(root: Path, rel: str, *, allow_final_symlink: bool = False) -> Path:
    pure = PurePosixPath(rel)
    if not rel or pure.is_absolute() or ".." in pure.parts or not pure.parts:
        raise ValueError(f"path must be a relative path inside the repository: {rel!r}")
    # root 自体が symlink 配下（macOS の /var 等）でも、その先を基準にする
    current = root.resolve()
    for part in pure.parts[:-1]:
        current = current / part
        if current.is_symlink():
            raise SymlinkConflict(f"ancestor is a symlink: {current}")
    final = current / pure.parts[-1]
    if not allow_final_symlink and final.is_symlink():
        raise SymlinkConflict(f"path is a symlink: {final}")
    return final


# --- classification ---------------------------------------------------------


class FileStatus(StrEnum):
    NEW = "NEW"
    UNCHANGED = "UNCHANGED"
    CLEAN_UPDATE = "CLEAN_UPDATE"
    USER_MODIFIED = "USER_MODIFIED"
    USER_OWNED = "USER_OWNED"
    SYMLINK_CONFLICT = "SYMLINK_CONFLICT"


def _classify_symlink(
    target_path: Path, entry: ManifestEntry | None, change: PlannedChange
) -> FileStatus:
    current_target = os.readlink(target_path)
    if entry is None or entry.kind != "symlink":
        return FileStatus.USER_OWNED if change.action == "LINK" else FileStatus.SYMLINK_CONFLICT
    if entry.link_target != current_target:
        return FileStatus.USER_MODIFIED
    if change.content is not None and change.content.decode("utf-8") == current_target:
        return FileStatus.UNCHANGED
    return FileStatus.CLEAN_UPDATE


def classify_change(
    root: Path,
    manifest: OwnershipManifest,
    change: PlannedChange,
    *,
    base_sha256: str | None = None,
) -> FileStatus:
    try:
        target = _check_path(root, change.path, allow_final_symlink=True)
    except SymlinkConflict:
        return FileStatus.SYMLINK_CONFLICT
    entry = manifest.get(change.path)
    if target.is_symlink():
        return _classify_symlink(target, entry, change)
    if not target.exists():
        return FileStatus.NEW
    current = target.read_bytes()
    if change.content is not None and current == change.content:
        return FileStatus.UNCHANGED
    recorded = entry.sha256 if entry is not None else base_sha256
    if recorded is None:
        return FileStatus.USER_OWNED
    if _sha256(current) == recorded:
        return FileStatus.CLEAN_UPDATE
    return FileStatus.USER_MODIFIED if entry is not None else FileStatus.USER_OWNED


# --- three-way diff ---------------------------------------------------------


@dataclass(frozen=True)
class ThreeWayDiff:
    path: str
    base: bytes | None
    current: bytes | None
    proposed: bytes | None


def _unified(path: str, old: bytes | None, new: bytes | None, labels: tuple[str, str]) -> str:
    old_lines = (old or b"").decode("utf-8", errors="replace").splitlines(keepends=True)
    new_lines = (new or b"").decode("utf-8", errors="replace").splitlines(keepends=True)
    return "".join(
        difflib.unified_diff(old_lines, new_lines, f"{path} ({labels[0]})", f"{path} ({labels[1]})")
    )


def render_three_way(diff: ThreeWayDiff) -> str:
    user_changes = _unified(diff.path, diff.base, diff.current, ("base", "current"))
    seh_changes = _unified(diff.path, diff.current, diff.proposed, ("current", "proposed"))
    return (
        f"# user changes (base -> current)\n{user_changes}\n"
        f"# proposed (current -> proposed)\n{seh_changes}"
    )


# --- transaction ------------------------------------------------------------


def _snapshot_dir(root: Path, snapshot_root: Path | None, snapshot_id: str) -> Path:
    return (snapshot_root or root / _DEFAULT_SNAPSHOT_DIR) / snapshot_id


def _read_journal(directory: Path) -> dict[str, Any]:
    return json.loads((directory / "journal.json").read_text(encoding="utf-8"))


def _write_journal(directory: Path, journal: dict[str, Any]) -> None:
    text = json.dumps(journal, indent=2, sort_keys=True) + "\n"
    atomic_write(directory / "journal.json", text.encode("utf-8"))


def _restore_entry(root: Path, directory: Path, entry: dict[str, Any]) -> None:
    target = _check_path(root, entry["path"], allow_final_symlink=True)
    kind = entry["kind"]
    if kind == "file":
        backup = (directory / entry["backup"]).read_bytes()
        atomic_write(target, backup, mode=entry["mode"])
    elif kind == "symlink":
        _atomic_symlink(target, entry["link_target"])
    elif target.is_symlink() or target.exists():
        target.unlink()
    for created in entry["created_dirs"]:
        # 作成した空ディレクトリだけを戻す。ユーザーのファイルが入っていれば残す
        with contextlib.suppress(OSError):
            (root.resolve() / created).rmdir()


def rollback(root: Path, snapshot_id: str, *, snapshot_root: Path | None = None) -> list[str]:
    directory = _snapshot_dir(root, snapshot_root, snapshot_id)
    journal = _read_journal(directory)
    restored: list[str] = []
    for entry in reversed(journal["entries"]):
        _restore_entry(root, directory, entry)
        if entry["path"] not in restored:
            restored.append(entry["path"])
    journal["status"] = "rolled_back"
    _write_journal(directory, journal)
    return restored


def recover_incomplete(root: Path, *, snapshot_root: Path | None = None) -> list[str]:
    base = snapshot_root or root / _DEFAULT_SNAPSHOT_DIR
    if not base.is_dir():
        return []
    recovered: list[str] = []
    for directory in sorted(base.iterdir()):
        if not (directory / "journal.json").is_file():
            continue
        if _read_journal(directory)["status"] != "in_progress":
            continue
        rollback(root, directory.name, snapshot_root=snapshot_root)
        recovered.append(directory.name)
    return recovered


class Transaction:
    def __init__(self, root: Path, *, snapshot_root: Path | None = None) -> None:
        self._root = root
        self._snapshot_root = snapshot_root
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        self.snapshot_id = f"{stamp}-{secrets.token_hex(3)}"
        self._dir = _snapshot_dir(root, snapshot_root, self.snapshot_id)
        self._journal: dict[str, Any] = {
            "snapshot_id": self.snapshot_id,
            "status": "in_progress",
            "entries": [],
        }
        _write_journal(self._dir, self._journal)

    def __enter__(self) -> Transaction:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if exc_type is None:
            self._journal["status"] = "committed"
            _write_journal(self._dir, self._journal)
            return
        rollback(self._root, self.snapshot_id, snapshot_root=self._snapshot_root)

    def _missing_parents(self, rel: str) -> list[str]:
        missing: list[str] = []
        pure = PurePosixPath(rel)
        for depth in range(1, len(pure.parts)):
            sub = PurePosixPath(*pure.parts[:depth])
            if not (self._root.resolve() / sub).exists():
                missing.append(str(sub))
        return sorted(missing, key=len, reverse=True)

    def _snapshot(self, rel: str, target: Path) -> None:
        """変更前の状態を退避し、journal を適用前に永続化する（kill されても戻せる）。"""
        entry: dict[str, Any] = {
            "path": rel,
            "kind": "absent",
            "created_dirs": self._missing_parents(rel),
        }
        if target.is_symlink():
            entry.update(kind="symlink", link_target=os.readlink(target))
        elif target.is_dir():
            raise ValueError(f"path is a directory: {rel!r}")
        elif target.exists():
            backup = f"files/{len(self._journal['entries'])}"
            atomic_write(self._dir / backup, target.read_bytes())
            entry.update(kind="file", backup=backup, mode=target.stat().st_mode & 0o777)
        self._journal["entries"].append(entry)
        _write_journal(self._dir, self._journal)

    def write(self, path: str, data: bytes) -> None:
        target = _check_path(self._root, path)
        self._snapshot(path, target)
        atomic_write(target, data)

    def delete(self, path: str) -> None:
        target = _check_path(self._root, path)
        self._snapshot(path, target)
        with contextlib.suppress(FileNotFoundError):
            target.unlink()

    def replace_symlink(self, path: str, target: str) -> None:
        link = _check_path(self._root, path, allow_final_symlink=True)
        self._snapshot(path, link)
        _atomic_symlink(link, target)

    def remove_symlink(self, path: str) -> None:
        link = _check_path(self._root, path, allow_final_symlink=True)
        if not link.is_symlink():
            raise ValueError(f"not a symlink: {path!r}")
        self._snapshot(path, link)
        link.unlink()
