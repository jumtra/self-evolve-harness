"""Provider 間の記憶コピー。移行元からは削除しない（旧データ保持）。"""

from __future__ import annotations

from dataclasses import dataclass, field

from seh.contracts.module import MemoryProvider, MemoryRecord


@dataclass
class MigrationReport:
    copied: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)


def copy_memories(src: MemoryProvider, dst: MemoryProvider) -> MigrationReport:
    report = MigrationReport()
    listed = src.list()
    if not listed.ok:
        report.errors.append(f"{listed.status}: {listed.message}")
        return report
    records = listed.data
    if not isinstance(records, list):
        report.errors.append("list の結果が不正です")
        return report
    for record in records:
        if not isinstance(record, MemoryRecord):
            report.skipped += 1
            continue
        saved = dst.save(record)
        if saved.ok:
            report.copied += 1
        else:
            report.errors.append(f"{record.id}: {saved.message}")
    return report
