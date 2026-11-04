"""Scheduler 状態と試行記録の永続化。強制終了後に状態・残り予算を復元する。"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from seh.contracts import TerminalState
from seh.ownership import atomic_write
from seh.runtime.repair import AttemptRecord
from seh.runtime.scheduler import Budget, SchedulerState


@dataclass(frozen=True)
class Checkpoint:
    state: SchedulerState
    budget_spent: Mapping[str, float]
    attempts: Mapping[str, tuple[AttemptRecord, ...]]
    task_summary: Mapping[str, object] = field(default_factory=dict)


def _runs_dir(root: Path) -> Path:
    return root / ".harness" / "state" / "runs"


def _record_to_dict(record: AttemptRecord) -> dict[str, object]:
    return {
        "attempt": record.attempt,
        "run_id": record.run_id,
        "terminal_state": record.terminal_state.value,
        "verdict_status": record.verdict_status,
        "reason_code": record.reason_code,
        "evidence_refs": list(record.evidence_refs),
    }


def _record_from_dict(data: Mapping[str, object]) -> AttemptRecord:
    verdict_status = data["verdict_status"]
    reason_code = data["reason_code"]
    refs = data["evidence_refs"]
    assert isinstance(refs, list)
    return AttemptRecord(
        int(str(data["attempt"])),
        str(data["run_id"]),
        TerminalState(str(data["terminal_state"])),
        None if verdict_status is None else str(verdict_status),
        None if reason_code is None else str(reason_code),
        tuple(str(r) for r in refs),
    )


class CheckpointStore:
    def __init__(self, root: Path, run_id: str) -> None:
        self._dir = _runs_dir(root) / run_id

    @staticmethod
    def list_runs(root: Path) -> list[str]:
        runs = _runs_dir(root)
        if not runs.is_dir():
            return []
        return sorted(p.name for p in runs.iterdir() if (p / "state.json").is_file())

    def save_state(
        self,
        state: SchedulerState,
        *,
        budget_spent: Mapping[str, float],
        task_summary: Mapping[str, object] | None = None,
    ) -> None:
        payload = {
            **state.to_dict(),
            "budget_spent": dict(budget_spent),
            "task_spec": dict(task_summary or {}),
        }
        atomic_write(self._dir / "state.json", json.dumps(payload, ensure_ascii=False).encode())

    def append_attempt(self, node_id: str, record: AttemptRecord) -> None:
        path = self._dir / "attempts" / f"{node_id}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(_record_to_dict(record), ensure_ascii=False) + "\n"
        with path.open("a", encoding="utf-8") as f:
            f.write(line)
            f.flush()
            os.fsync(f.fileno())

    def load(self) -> Checkpoint | None:
        state_path = self._dir / "state.json"
        if not state_path.is_file():
            return None
        data = json.loads(state_path.read_text(encoding="utf-8"))
        spent = data.get("budget_spent", {})
        summary = data.get("task_spec", {})
        return Checkpoint(
            SchedulerState.from_dict(data),
            {k: float(v) for k, v in spent.items()},
            self._load_attempts(),
            summary,
        )

    def _load_attempts(self) -> dict[str, tuple[AttemptRecord, ...]]:
        attempts_dir = self._dir / "attempts"
        if not attempts_dir.is_dir():
            return {}
        return {
            p.stem: tuple(
                _record_from_dict(json.loads(line))
                for line in p.read_text(encoding="utf-8").splitlines()
                if line.strip()
            )
            for p in sorted(attempts_dir.glob("*.jsonl"))
        }


def next_attempt(attempts_for_node: tuple[AttemptRecord, ...]) -> int:
    return max((a.attempt for a in attempts_for_node), default=0) + 1


def remaining_budget(total: Budget, spent: Mapping[str, float]) -> Budget:
    cost = total.max_cost_usd
    return Budget(
        total.max_parallel,
        max(0.0, total.max_total_seconds - spent.get("elapsed_seconds", 0.0)),
        None if cost is None else max(0.0, cost - spent.get("cost_usd", 0.0)),
    )
