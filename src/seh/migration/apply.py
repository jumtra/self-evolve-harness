from __future__ import annotations

import contextlib
import os
from collections.abc import Collection
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from seh.migration import inventory
from seh.migration.planner import MigrationAction, MigrationItem, MigrationPlan
from seh.ownership import Transaction, recover_incomplete

__all__ = ["MigrationResult", "PlanInvalid", "PlanStale", "apply_migration"]


class PlanStale(Exception):
    """計画作成後に現物が変わった。何も変更せず中止する。"""


class PlanInvalid(Exception):
    """計画が v1 既知パス・baseline と整合しない（改ざんの疑い）。"""


@dataclass(frozen=True)
class MigrationResult:
    snapshot_id: str
    deleted: list[str]
    skipped: list[str]


_REMOVING = (MigrationAction.DELETE, MigrationAction.REWRITE, MigrationAction.MOVE)


def _validate(plan: MigrationPlan, approve: Collection[str]) -> None:
    _, known = inventory.load_known_paths()
    conflicts = {i.path for i in plan.items if i.action is MigrationAction.USER_OWNED_CONFLICT}
    unknown = sorted(set(approve) - conflicts)
    if unknown:
        raise ValueError(f"承認対象が計画上の競合ではありません: {', '.join(unknown)}")
    for item in plan.items:
        if item.action not in _REMOVING:
            continue
        info = known.get(item.path)
        if (
            info is None
            or info.v2_action != item.action.value
            or item.current_sha256 != info.sha256
        ):
            raise PlanInvalid(f"計画が v1 baseline と整合しません: {item.path}")


def _check_fresh(root: Path, items: list[MigrationItem]) -> None:
    stale = [i.path for i in items if inventory.fingerprint(root, i.path) != i.current_sha256]
    if stale:
        raise PlanStale(f"計画後に変更されています: {', '.join(stale)}")


def _delete_item(tx: Transaction, root: Path, rel: str) -> None:
    path = root / rel
    if path.is_symlink():
        tx.remove_symlink(rel)
    elif path.is_dir():
        for current, dirnames, filenames in os.walk(path, followlinks=False):
            base = Path(current).relative_to(root).as_posix()
            for name in sorted(filenames):
                tx.delete(f"{base}/{name}")
            for name in sorted(dirnames):
                if (Path(current) / name).is_symlink():
                    tx.remove_symlink(f"{base}/{name}")
    else:
        tx.delete(rel)


def _prune_empty_dirs(root: Path, rel: str) -> None:
    path = root / rel
    if path.is_dir() and not path.is_symlink():
        for current, _, _ in os.walk(path, topdown=False, followlinks=False):
            with contextlib.suppress(OSError):
                Path(current).rmdir()
    # トップレベル（.claude 等）はユーザー領域なので、空でも残す
    for parent in PurePosixPath(rel).parents:
        if len(parent.parts) < 2:
            break
        try:
            (root / parent).rmdir()
        except OSError:
            break


def apply_migration(
    root: Path, plan: MigrationPlan, *, approve_conflicts: Collection[str] = ()
) -> MigrationResult:
    recover_incomplete(root)
    _validate(plan, approve_conflicts)
    approved = set(approve_conflicts)
    targets: list[MigrationItem] = []
    skipped: list[str] = []
    for item in plan.items:
        if item.action in _REMOVING or (
            item.action is MigrationAction.USER_OWNED_CONFLICT and item.path in approved
        ):
            targets.append(item)
        elif item.action is MigrationAction.USER_OWNED_CONFLICT:
            skipped.append(item.path)
    _check_fresh(root, [i for i in plan.items if i.action is not MigrationAction.KEEP])
    with Transaction(root) as tx:
        for item in targets:
            _delete_item(tx, root, item.path)
        snapshot_id = tx.snapshot_id
    for item in targets:
        _prune_empty_dirs(root, item.path)
    return MigrationResult(snapshot_id, [i.path for i in targets], skipped)
