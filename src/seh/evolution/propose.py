"""変更案を独立 worktree に作り、保護パスへの変更を拒否する。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from seh.policy import is_protected_path, is_sensitive_path
from seh.runtime.worktree import UnitWorkspace, WorktreeManager


class ProposalError(ValueError):
    """候補の書込先が不正または保護されている。"""


@dataclass(frozen=True)
class Candidate:
    workspace: UnitWorkspace
    changed_paths: tuple[str, ...]


def _check_path(path: str) -> None:
    parts = PurePosixPath(path).parts
    if (
        not path
        or "\\" in path
        or PurePosixPath(path).is_absolute()
        or any(part in (".", "..", ".git") for part in parts)
        or parts[:2]
        in {
            (".harness", "state"),
            (".harness", "evolution"),
            (".harness", "knowledge"),
            (".harness", "artifacts"),
        }
        or is_protected_path(path)
        or is_sensitive_path(path)
    ):
        raise ProposalError(f"unsafe candidate path: {path}")


def _check_symlinks(root: Path, path: str) -> None:
    current = root
    for part in PurePosixPath(path).parts:
        current = current / part
        if current.is_symlink():
            raise ProposalError(f"symlink in candidate path: {path}")


async def propose(
    repo: Path, *, run_id: str, candidate_id: str, changes: Mapping[str, str]
) -> Candidate:
    """文字列の変更案を適用する。外部コマンドや任意の生成器は実行しない。"""
    for path in changes:
        _check_path(path)
    manager = WorktreeManager(repo, run_id=run_id)
    base = await manager.base_commit()
    workspace = await manager.create(candidate_id, base=base)
    try:
        for path in changes:
            _check_symlinks(workspace.path, path)
        for path, content in changes.items():
            destination = workspace.path / path
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(content, encoding="utf-8")
        changed = await manager.changed_paths(workspace)
        for path in changed:
            _check_path(path)
        return Candidate(workspace, changed)
    except Exception:
        await manager.cleanup()
        raise
