from __future__ import annotations

from pathlib import Path

from seh import ownership

__all__ = ["rollback_migration"]


def rollback_migration(root: Path, snapshot_id: str) -> list[str]:
    return ownership.rollback(root, snapshot_id)
