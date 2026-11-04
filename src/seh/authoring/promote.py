"""昇格と巻き戻し。正本への書込は Transaction で行い、失敗時は元の正本が残る。"""

from __future__ import annotations

import json
import re
from collections import deque
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from seh.authoring.gate import GateDecision, GateStatus, record_to_json
from seh.authoring.spec import load_record
from seh.contracts import AuthoringRecord, AuthoringState, transition_authoring
from seh.contracts.authoring import AUTHORING_TRANSITIONS
from seh.ownership import Transaction, atomic_write, rollback

AUTHORING_DIR = Path(".harness") / "authoring"
PROMOTIONS_LOG = AUTHORING_DIR / "promotions.jsonl"
SPEC_DIR = ".harness/spec"
_RECORD_ID = re.compile(r"[A-Za-z0-9._-]+")


class PromotionRefused(Exception):
    pass


def record_path(root: Path, record_id: str) -> Path:
    if not _RECORD_ID.fullmatch(record_id) or record_id in (".", ".."):
        raise ValueError(f"invalid record id: {record_id!r}")
    return root / AUTHORING_DIR / f"{record_id}.json"


def save_record(root: Path, record: AuthoringRecord) -> Path:
    path = record_path(root, record.id)
    text = json.dumps(record_to_json(record), ensure_ascii=False, indent=2) + "\n"
    atomic_write(path, text.encode("utf-8"))
    return path


def load_records(root: Path) -> list[AuthoringRecord]:
    directory = root / AUTHORING_DIR
    if not directory.is_dir():
        return []
    return [load_record(p) for p in sorted(directory.glob("*.json"))]


def _route(record: AuthoringRecord, goal: AuthoringState) -> list[AuthoringState] | None:
    """遷移表と can_transition（承認条件）に従う最短経路。無ければ None。"""
    queue: deque[tuple[AuthoringRecord, list[AuthoringState]]] = deque([(record, [])])
    seen = {record.state}
    while queue:
        current, path = queue.popleft()
        if current.state is goal:
            return path
        for nxt in sorted(AUTHORING_TRANSITIONS[current.state]):
            if nxt not in seen and current.can_transition(nxt):
                seen.add(nxt)
                queue.append((replace(current, state=nxt), [*path, nxt]))
    return None


def _advance(record: AuthoringRecord, goal: AuthoringState) -> AuthoringRecord | None:
    route = _route(record, goal)
    if route is None:
        return None
    for state in route:
        record = transition_authoring(record, state)
    return record


def _read_promotions(root: Path) -> list[dict[str, object]]:
    path = root / PROMOTIONS_LOG
    if not path.is_file():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    return [cast("dict[str, object]", json.loads(line)) for line in lines if line.strip()]


def promote(
    root: Path, record: AuthoringRecord, decision: GateDecision, *, candidate_dir: Path
) -> str:
    if decision.status is not GateStatus.PASS:
        raise PromotionRefused(f"{decision.status.value}: {', '.join(decision.reasons)}")
    promoted = _advance(record, AuthoringState.PROMOTED)
    if promoted is None:
        raise PromotionRefused(f"state {record.state.value} cannot be promoted")
    sources = sorted(p for p in candidate_dir.rglob("*") if p.is_file())
    if not sources:
        raise PromotionRefused("candidate has no files")
    written = [f"{SPEC_DIR}/{p.relative_to(candidate_dir).as_posix()}" for p in sources]
    with Transaction(root) as tx:
        for source, rel in zip(sources, written, strict=True):
            tx.write(rel, source.read_bytes())
    promotion_id = tx.snapshot_id
    try:
        entry = {
            "promotion_id": promotion_id,
            "record_id": record.id,
            "at": datetime.now(UTC).isoformat(),
            "files": written,
        }
        log = root / PROMOTIONS_LOG
        previous = log.read_bytes() if log.is_file() else b""
        line = json.dumps(entry, ensure_ascii=False) + "\n"
        atomic_write(log, previous + line.encode("utf-8"))
        save_record(root, promoted)
    except BaseException:
        rollback(root, promotion_id)
        raise
    return promotion_id


def rollback_promotion(root: Path, promotion_id: str) -> list[str]:
    entry = next((e for e in _read_promotions(root) if e["promotion_id"] == promotion_id), None)
    if entry is None:
        raise KeyError(promotion_id)
    restored = rollback(root, promotion_id)
    path = record_path(root, cast("str", entry["record_id"]))
    if path.is_file():
        record = load_record(path)
        if record.state is not AuthoringState.ROLLED_BACK:
            save_record(root, transition_authoring(record, AuthoringState.ROLLED_BACK))
    return restored
