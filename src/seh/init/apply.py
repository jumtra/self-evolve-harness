"""`seh init --apply`: 設定・正本 spec → v1 移行 → sync を一連で適用し、失敗時は全て戻す。"""

from __future__ import annotations

import contextlib
import hashlib
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from pathlib import Path

from seh import ownership
from seh.contracts import DiagnosticLevel
from seh.init.planner import CONFIG_PATH, InitPlan, load_spec_files
from seh.init.templating import InitError
from seh.migration.apply import apply_migration
from seh.migration.planner import MigrationAction
from seh.ownership import (
    MANIFEST_PATH,
    OwnershipManifest,
    Transaction,
    atomic_write,
    recover_incomplete,
)
from seh.sync import LOCK_PATH, SyncPlan, apply_sync, plan_sync

__all__ = ["InitResult", "apply_init", "merge_gitignore"]

_BEGIN = "# seh:begin\n"
_END = "# seh:end\n"
_BACKUPS = Path(".harness") / "backups"


@dataclass(frozen=True)
class InitResult:
    written: list[str]
    migration_snapshot: str | None
    rolled_back: bool


def merge_gitignore(current: str, block: str) -> str:
    begin = current.find(_BEGIN)
    end = current.find(_END, begin) if begin >= 0 else -1
    if begin >= 0 and end >= 0:
        return current[:begin] + block + current[end + len(_END) :]
    if not current:
        return block
    return f"{current}{'' if current.endswith(chr(10)) else chr(10)}{block}"


def _paths(plan: SyncPlan) -> set[str]:
    # 移行で旧ファイルが消えると衝突が通常の書込に変わるため、items と conflicts を併せて比較する
    return {i.path for i in (*plan.items, *plan.conflicts)}


def _snapshot_ids(root: Path) -> set[str]:
    base = root / _BACKUPS
    return {p.name for p in base.iterdir()} if base.is_dir() else set()


def _read_or_none(path: Path) -> bytes | None:
    return path.read_bytes() if path.is_file() else None


def _restore(path: Path, data: bytes | None) -> None:
    if data is None:
        with contextlib.suppress(FileNotFoundError):
            path.unlink()
    else:
        atomic_write(path, data)


def _validate_plan(plan: InitPlan, approve: Collection[str]) -> None:
    errors = [d for d in plan.sync.diagnostics if d.level is DiagnosticLevel.ERROR]
    collisions = [c.path for c in plan.sync.conflicts if c.status == "CONTENT_COLLISION"]
    if errors or collisions:
        raise InitError("sync 計画に ERROR または内容衝突があるため適用できません")
    known = {c.path for c in plan.sync.conflicts}
    if plan.migration is not None:
        known |= {
            i.path for i in plan.migration.items if i.action is MigrationAction.USER_OWNED_CONFLICT
        }
    unknown = sorted(set(approve) - known)
    if unknown:
        raise InitError(f"承認対象が計画上の競合ではありません: {', '.join(unknown)}")


def apply_init(
    root: Path,
    plan: InitPlan,
    *,
    approve_conflicts: Collection[str] = (),
    seh_version: str,
    cli_versions: Mapping[str, str | None],
) -> InitResult:
    root = Path(root)
    approve = set(approve_conflicts)
    recover_incomplete(root)
    _validate_plan(plan, approve)

    written: list[str] = []
    snapshots_before = _snapshot_ids(root)
    manifest_before = _read_or_none(root / MANIFEST_PATH)
    lock_before = _read_or_none(root / LOCK_PATH)
    config_snapshot: str | None = None
    migration_snapshot: str | None = None
    try:
        with Transaction(root) as tx:
            config_snapshot = tx.snapshot_id
            tx.write(CONFIG_PATH, plan.config_toml.encode("utf-8"))
            written.append(CONFIG_PATH)
            for rel, data in sorted(plan.spec_files.items()):
                tx.write(rel, data)
                written.append(rel)
            gitignore = root / ".gitignore"
            current = gitignore.read_text(encoding="utf-8") if gitignore.is_file() else ""
            merged = merge_gitignore(current, plan.gitignore_block)
            if merged != current:
                tx.write(".gitignore", merged.encode("utf-8"))
                written.append(".gitignore")

        # 正本の初回導入を D13（Authoring Gate 対象外）の判定材料にする。
        # apply_sync は manifest を読み直して更新するため、この記録は消えない
        manifest = OwnershipManifest.load(root)
        for rel, data in plan.spec_files.items():
            manifest.record(rel, hashlib.sha256(data).hexdigest(), "init", seh_version)
        manifest.save(root)

        if plan.migration is not None:
            migration_conflicts = {
                i.path
                for i in plan.migration.items
                if i.action is MigrationAction.USER_OWNED_CONFLICT
            }
            result = apply_migration(
                root, plan.migration, approve_conflicts=sorted(approve & migration_conflicts)
            )
            migration_snapshot = result.snapshot_id

        spec = load_spec_files(plan.spec_files)
        sync = plan_sync(root, plan.config.hosts.enabled, spec=spec)
        if _paths(sync) != _paths(plan.sync):
            raise InitError("計画と状態が食い違いました。再度 --plan してください")
        overwrite = sorted(approve & {c.path for c in sync.conflicts})
        written += apply_sync(
            root, sync, overwrite=overwrite, seh_version=seh_version, cli_versions=cli_versions
        )
    except BaseException as error:
        rolled = _rollback_all(
            root,
            snapshots_before,
            config_snapshot,
            migration_snapshot,
            manifest_before,
            lock_before,
        )
        error.add_note(
            "init をロールバックしました" if rolled else "init のロールバックに失敗しました"
        )
        raise
    return InitResult(written, migration_snapshot, rolled_back=False)


def _rollback_all(
    root: Path,
    snapshots_before: set[str],
    config_snapshot: str | None,
    migration_snapshot: str | None,
    manifest_before: bytes | None,
    lock_before: bytes | None,
) -> bool:
    """sync → 移行 → 設定の逆順で戻す。各段の失敗は握りつぶさず、最後に成否を返す。"""
    ok = True
    # sync 内部の Transaction は commit 済みでも、その後の manifest/lock 書込失敗で呼出側に戻るため
    created = sorted(_snapshot_ids(root) - snapshots_before, reverse=True)
    known = {config_snapshot, migration_snapshot}
    steps = [s for s in created if s not in known]
    if migration_snapshot is not None:
        steps.append(migration_snapshot)
    if config_snapshot is not None:
        steps.append(config_snapshot)
    for snapshot_id in steps:
        try:
            ownership.rollback(root, snapshot_id)
        except Exception:
            ok = False
    for rel, data in ((MANIFEST_PATH, manifest_before), (Path(LOCK_PATH), lock_before)):
        try:
            _restore(root / rel, data)
        except Exception:
            ok = False
    return ok
