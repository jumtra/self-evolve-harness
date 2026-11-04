"""自己進化の入力（feedback / 失敗 / Hook 遮断 / eval 退行）を read-only で集約する。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path

from seh.contracts.module import MemoryProvider, MemoryRecord
from seh.providers.memory.base import slugify
from seh.redaction import mask_text

_SUMMARY_MAX = 200
_FEEDBACK_THRESHOLD = 3
_RUN_THRESHOLD = 2
_FAIL_STATUSES = frozenset({"FAIL", "FAILED"})
_BLOCK_DECISIONS = frozenset({"deny", "ask"})


class ObservationKind(StrEnum):
    FEEDBACK = "feedback"
    UNIT_FAILURE = "unit_failure"
    HOOK_BLOCK = "hook_block"
    EVAL_REGRESSION = "eval_regression"


_KIND_ORDER = {kind: i for i, kind in enumerate(ObservationKind)}


@dataclass(frozen=True)
class Observation:
    key: str
    kind: ObservationKind
    count: int
    evidence_refs: tuple[str, ...]
    first_seen: str
    last_seen: str
    summary: str
    actionable: bool


@dataclass(frozen=True)
class ObserveReport:
    observations: list[Observation]
    last_errors: int


@dataclass(frozen=True)
class _Hit:
    kind: ObservationKind
    key: str
    unit: str  # 同一失敗の重複カウントを避ける単位
    group: str  # actionable 判定で「異なる run」を数える単位
    weight: int
    ref: str
    ts: datetime
    text: str


def _parse_ts(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _read_jsonl(path: Path) -> tuple[list[dict], bool]:
    """壊れた行は捨てる。読めない/壊れがあれば第 2 要素が True。"""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return [], True
    rows: list[dict] = []
    broken = False
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            broken = True
            continue
        if isinstance(row, dict):
            rows.append(row)
        else:
            broken = True
    return rows, broken


def _feedback_hits(memory: MemoryProvider, now: datetime) -> tuple[list[_Hit], int]:
    listed = memory.list()
    records = listed.data
    if not isinstance(records, list):
        return [], 1
    hits: list[_Hit] = []
    for record in records:
        if not isinstance(record, MemoryRecord) or record.type != "feedback":
            continue
        if record.metadata.get("evolve", "pending") != "pending":
            continue
        raw_count = record.metadata.get("count", 1)
        weight = raw_count if isinstance(raw_count, int) and raw_count > 0 else 1
        # 記録に時刻が無い provider もあるため、無ければ今の事象として扱う
        seen = _parse_ts(record.metadata.get("last_seen")) or now
        hits.append(
            _Hit(
                ObservationKind.FEEDBACK,
                f"feedback:{slugify(record.title)}",
                record.id,
                record.id,
                weight,
                f"memory:{record.id}",
                seen,
                record.title,
            )
        )
    return hits, 0


def _attempt_hits(root: Path) -> tuple[list[_Hit], int]:
    hits: list[_Hit] = []
    errors = 0
    for path in sorted((root / ".harness/state/runs").glob("*/attempts/*.jsonl")):
        run_id = path.parent.parent.name
        node_id = path.stem
        rows, broken = _read_jsonl(path)
        errors += broken
        try:
            seen = datetime.fromtimestamp(path.stat().st_mtime, UTC)
        except OSError:
            continue
        for row in rows:
            reason = row.get("reason_code")
            failed = row.get("verdict_status") in _FAIL_STATUSES or row.get("terminal_state") in (
                _FAIL_STATUSES
            )
            if not failed or not isinstance(reason, str) or not reason:
                continue
            hits.append(
                _Hit(
                    ObservationKind.UNIT_FAILURE,
                    f"failure:{reason}",
                    f"{run_id}:{node_id}",
                    run_id,
                    1,
                    f"attempt:{run_id}:{node_id}:{row.get('attempt', 0)}",
                    seen,
                    f"unit failure {reason} (node {node_id})",
                )
            )
    return hits, errors


def _hook_hits(root: Path) -> tuple[list[_Hit], int]:
    path = root / ".harness/state/hook-trace.jsonl"
    if not path.is_file():
        return [], 0
    rows, broken = _read_jsonl(path)
    hits: list[_Hit] = []
    for row in rows:
        data = row.get("data")
        ts = _parse_ts(row.get("ts"))
        if not isinstance(data, dict) or ts is None:
            continue
        reason = data.get("reason_code")
        decision = str(data.get("decision", "")).lower()
        if decision not in _BLOCK_DECISIONS or not isinstance(reason, str) or not reason:
            continue
        run_id = str(row.get("run_id", ""))
        event_id = str(row.get("event_id", ""))
        hits.append(
            _Hit(
                ObservationKind.HOOK_BLOCK,
                f"hook:{reason}",
                f"{run_id}:{event_id}",
                run_id,
                1,
                f"trace:{run_id}:{event_id}",
                ts,
                f"hook {decision} {reason}",
            )
        )
    return hits, int(broken)


def _eval_hits(root: Path) -> tuple[list[_Hit], int]:
    errors = 0
    runs: list[tuple[datetime, str, dict[str, bool]]] = []
    paths = [
        *sorted((root / ".harness/artifacts/eval").glob("*.json")),
        *sorted((root / ".harness/authoring/evals").glob("*.json")),
    ]
    for path in paths:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            created = _parse_ts(data["created_at"])
            trials = data["trials"]
            if created is None or not isinstance(trials, list):
                raise ValueError(path.name)
            passed: dict[str, bool] = {}
            for trial in trials:
                case_id = str(trial["case_id"])
                ok = trial["verdict_status"] == "PASS"
                passed[case_id] = passed.get(case_id, True) and ok
        except (OSError, ValueError, KeyError, TypeError, UnicodeDecodeError):
            errors += 1
            continue
        runs.append((created, str(data.get("run_id", path.stem)), passed))
    runs.sort(key=lambda r: (r[0], r[1]))
    hits: list[_Hit] = []
    for (_, _, before), (created, run_id, after) in zip(runs, runs[1:], strict=False):
        for case_id, ok in after.items():
            if ok or not before.get(case_id, False):
                continue
            hits.append(
                _Hit(
                    ObservationKind.EVAL_REGRESSION,
                    f"eval:{case_id}",
                    f"{run_id}:{case_id}",
                    run_id,
                    1,
                    f"eval:{run_id}:{case_id}",
                    created,
                    f"eval case {case_id} regressed PASS to FAIL",
                )
            )
    return hits, errors


def _actionable(kind: ObservationKind, count: int, groups: int) -> bool:
    if kind is ObservationKind.FEEDBACK:
        return count >= _FEEDBACK_THRESHOLD
    if kind is ObservationKind.EVAL_REGRESSION:
        return count >= 1
    return groups >= _RUN_THRESHOLD


def _aggregate(hits: list[_Hit]) -> list[Observation]:
    by_key: dict[str, list[_Hit]] = {}
    for hit in hits:
        by_key.setdefault(hit.key, []).append(hit)
    out: list[Observation] = []
    for key, group in by_key.items():
        kind = group[0].kind
        # 同一 unit は最大 weight の 1 件だけ数える（再試行の水増し防止）
        units: dict[str, int] = {}
        for hit in group:
            units[hit.unit] = max(units.get(hit.unit, 0), hit.weight)
        count = sum(units.values())
        first = min(h.ts for h in group)
        last = max(h.ts for h in group)
        summary = mask_text(f"{group[0].text} x{count}")[:_SUMMARY_MAX]
        out.append(
            Observation(
                mask_text(key),
                kind,
                count,
                tuple(sorted({mask_text(h.ref) for h in group})),
                first.isoformat(),
                last.isoformat(),
                summary,
                _actionable(kind, count, len({h.group for h in group})),
            )
        )
    out.sort(key=lambda o: (_KIND_ORDER[o.kind], -o.count, o.key))
    return out


def observe_with_errors(
    root: Path,
    *,
    memory: MemoryProvider | None,
    now: datetime,
    window_days: int = 90,
) -> ObserveReport:
    hits: list[_Hit] = []
    errors = 0
    sources = [_attempt_hits(root), _hook_hits(root), _eval_hits(root)]
    if memory is not None:
        sources.insert(0, _feedback_hits(memory, now))
    for found, err in sources:
        hits.extend(found)
        errors += err
    cutoff = now - timedelta(days=window_days)
    fresh = [h for h in hits if h.ts >= cutoff]
    return ObserveReport(_aggregate(fresh), errors)


def observe(
    root: Path,
    *,
    memory: MemoryProvider | None,
    now: datetime,
    window_days: int = 90,
) -> list[Observation]:
    return observe_with_errors(root, memory=memory, now=now, window_days=window_days).observations
