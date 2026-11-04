"""Rollback a known promotion only while its output has not changed."""

import json
import re
from pathlib import Path

from seh.evolution.benchmark import overlay_digest
from seh.evolution.propose import _check_path, _check_symlinks
from seh.ownership import rollback


def rollback_promotion(root: Path, snapshot_id: str) -> list[str]:
    if not re.fullmatch(r"[A-Za-z0-9_-]+", snapshot_id):
        raise ValueError("invalid snapshot id")
    record = root / ".harness/evolution/promotions" / f"{snapshot_id}.json"
    if not record.is_file() or record.is_symlink():
        raise ValueError("unknown evolution promotion")
    data = json.loads(record.read_text())
    if data.get("snapshot_id") != snapshot_id or not isinstance(data.get("paths"), list):
        raise ValueError("invalid evolution promotion")
    current = {}
    for path in data["paths"]:
        if not isinstance(path, str):
            raise ValueError("invalid promoted path")
        _check_path(path)
        _check_symlinks(root, path)
        current[path] = (root / path).read_bytes() if (root / path).is_file() else None
    if overlay_digest(current) != data.get("candidate_digest"):
        raise ValueError("promoted files changed since promotion")
    return rollback(root, snapshot_id)
