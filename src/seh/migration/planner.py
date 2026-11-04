from __future__ import annotations

import json
import secrets
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from seh.migration import inventory
from seh.migration.inventory import InventoryEntry
from seh.ownership import atomic_write

__all__ = [
    "MigrationAction",
    "MigrationItem",
    "MigrationPlan",
    "load_plan",
    "plan_migration",
    "save_plan",
]

_USER_DATA_PREFIX = ".agent-memory/"
_ALWAYS_KEEP = (".claude/settings.local.json", ".agents/skills.json")


class MigrationAction(StrEnum):
    KEEP = "KEEP"
    REWRITE = "REWRITE"
    MOVE = "MOVE"
    DELETE = "DELETE"
    USER_OWNED_CONFLICT = "USER_OWNED_CONFLICT"


@dataclass(frozen=True)
class MigrationItem:
    path: str
    action: MigrationAction
    reason: str
    current_sha256: str | None
    baseline_sha256: str | None
    diff: str | None = None


@dataclass(frozen=True)
class MigrationPlan:
    plan_id: str
    baseline_ref: str
    items: tuple[MigrationItem, ...]
    created_at: str


def _item(entry: InventoryEntry) -> MigrationItem:
    current = entry.sha256 if entry.sha256 is not None else f"symlink:{entry.link_target}"
    baseline = entry.known.sha256 if entry.known is not None else None

    def make(action: MigrationAction, reason: str, diff: str | None = None) -> MigrationItem:
        return MigrationItem(entry.path, action, reason, current, baseline, diff)

    if entry.path.startswith(_USER_DATA_PREFIX) or entry.path in _ALWAYS_KEEP:
        return make(MigrationAction.KEEP, "ユーザーデータ（常に保持）")
    if entry.is_symlink:
        return make(
            MigrationAction.USER_OWNED_CONFLICT,
            f"シンボリックリンク（リンク先: {entry.link_target}）",
        )
    if entry.known is None:
        return make(MigrationAction.USER_OWNED_CONFLICT, "ホスト生成先に既存物があります")
    if entry.sha256 == entry.known.sha256:
        action = MigrationAction(entry.known.v2_action)
        return make(action, f"v1 から未改変（{entry.known.kind}）")
    diff = f"現物 sha256: {entry.sha256}\nbaseline sha256: {entry.known.sha256}"
    return make(MigrationAction.USER_OWNED_CONFLICT, "v1 baseline と内容が異なります", diff)


def plan_migration(root: Path) -> MigrationPlan:
    baseline_ref, _ = inventory.load_known_paths()
    items = tuple(_item(e) for e in inventory.take_inventory(root) if e.exists)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return MigrationPlan(
        plan_id=f"{stamp}-{secrets.token_hex(3)}",
        baseline_ref=baseline_ref,
        items=items,
        created_at=datetime.now(UTC).isoformat(),
    )


def plan_to_dict(plan: MigrationPlan) -> dict[str, Any]:
    return asdict(plan)


def save_plan(root: Path, plan: MigrationPlan) -> Path:
    path = root / ".harness" / "state" / f"migrate-plan-{plan.plan_id}.json"
    text = json.dumps(plan_to_dict(plan), ensure_ascii=False, indent=2) + "\n"
    atomic_write(path, text.encode("utf-8"))
    return path


def load_plan(path: Path) -> MigrationPlan:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        items = tuple(
            MigrationItem(
                path=i["path"],
                action=MigrationAction(i["action"]),
                reason=i["reason"],
                current_sha256=i["current_sha256"],
                baseline_sha256=i["baseline_sha256"],
                diff=i.get("diff"),
            )
            for i in data["items"]
        )
        return MigrationPlan(data["plan_id"], data["baseline_ref"], items, data["created_at"])
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError(f"計画ファイルが不正です: {path}: {error}") from error
