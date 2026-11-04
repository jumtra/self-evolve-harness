"""正本 spec から 4 ホストの生成物を計画し、ownership に照らして安全に適用する（一方向）。"""

from __future__ import annotations

import difflib
import hashlib
import json
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from seh.contracts import (
    CanonicalSpec,
    ChangeAction,
    Diagnostic,
    DiagnosticLevel,
    GeneratedPlan,
    HostAdapter,
    HostCapability,
    HostId,
    PlannedChange,
    RenderContext,
    RiskRank,
)
from seh.ownership import (
    FileStatus,
    OwnershipManifest,
    ThreeWayDiff,
    Transaction,
    atomic_write,
    classify_change,
    recover_incomplete,
    render_three_way,
)
from seh.policy import classify_paths
from seh.providers.hosts.common import MANAGED_BEGIN, MANAGED_BLOCK_REASON, MANAGED_END
from seh.providers.hosts.discovery import discovery_collisions, static_discovery

__all__ = [
    "SyncError",
    "SyncItem",
    "SyncPlan",
    "apply_sync",
    "default_adapters",
    "plan_sync",
]

LOCK_PATH = ".harness/generated.lock.json"
# 内容衝突は FileStatus に無いため sync 側で足す（overwrite 不可）
SyncStatus = FileStatus | Literal["BLOCK_UPDATE", "BLOCK_INSERT", "CONTENT_COLLISION"]
_NOT_OVERWRITABLE = (FileStatus.SYMLINK_CONFLICT, "CONTENT_COLLISION")
_APPLICABLE = (FileStatus.NEW, FileStatus.UNCHANGED, FileStatus.CLEAN_UPDATE)


class SyncError(Exception):
    """sync の前提違反（overwrite 指定が不正など）。"""


@dataclass(frozen=True)
class SyncItem:
    path: str
    status: SyncStatus
    content: bytes
    owners: tuple[str, ...]
    risk: RiskRank
    diff: str | None = None
    # ownership にファイル全体ではなく管理ブロック部分の sha256 を記録する対象
    managed_block: bool = False


@dataclass(frozen=True)
class SyncPlan:
    items: tuple[SyncItem, ...]
    conflicts: tuple[SyncItem, ...]
    collisions: tuple[str, ...]
    diagnostics: tuple[Diagnostic, ...]
    capabilities: Mapping[HostId, tuple[HostCapability, ...]] = field(default_factory=dict)


def default_adapters() -> dict[HostId, HostAdapter]:
    from seh.providers.hosts.antigravity import AntigravityHostAdapter
    from seh.providers.hosts.claude import ClaudeHostAdapter
    from seh.providers.hosts.codex import CodexHostAdapter
    from seh.providers.hosts.opencode import OpenCodeHostAdapter

    return {
        HostId.CLAUDE: ClaudeHostAdapter(),
        HostId.ANTIGRAVITY: AntigravityHostAdapter(),
        HostId.CODEX: CodexHostAdapter(),
        HostId.OPENCODE: OpenCodeHostAdapter(),
    }


# --- 管理ブロック -----------------------------------------------------------------


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _block_span(text: str) -> tuple[int, int] | None:
    begin = text.find(MANAGED_BEGIN)
    if begin < 0:
        return None
    end = text.find(MANAGED_END, begin)
    if end < 0:
        return None
    end += len(MANAGED_END)
    if text[end : end + 1] == "\n":
        end += 1
    return begin, end


def extract_block(text: str) -> str:
    span = _block_span(text)
    return text[span[0] : span[1]] if span else text


def _recorded_sha(item: SyncItem) -> str:
    if item.managed_block:
        return _sha256(extract_block(item.content.decode("utf-8")).encode("utf-8"))
    return _sha256(item.content)


def _insert_block(text: str, block: str) -> str:
    if not text:
        return block
    separator = "\n" if text.endswith("\n") else "\n\n"
    return f"{text}{separator}{block}"


# --- 計画 -------------------------------------------------------------------------


def _unified(path: str, a: bytes, b: bytes) -> str:
    return "".join(
        difflib.unified_diff(
            a.decode("utf-8", errors="replace").splitlines(keepends=True),
            b.decode("utf-8", errors="replace").splitlines(keepends=True),
            f"{path} (variant 1)",
            f"{path} (variant 2)",
        )
    )


@dataclass(frozen=True)
class _Merged:
    path: str
    content: bytes
    is_block: bool
    owners: tuple[str, ...]


def _merge(
    changes: Sequence[PlannedChange],
) -> tuple[list[_Merged], dict[str, list[_Merged]]]:
    """同一パス・同一内容は owners を併記して 1 件に。異なる内容は衝突として返す。"""
    variants: dict[str, dict[tuple[bytes, bool], list[str]]] = {}
    for change in changes:
        if change.content is None:
            continue
        key = (change.content, change.reason == MANAGED_BLOCK_REASON)
        owners = variants.setdefault(change.path, {}).setdefault(key, [])
        if change.owner not in owners:
            owners.append(change.owner)
    merged: list[_Merged] = []
    collided: dict[str, list[_Merged]] = {}
    for path, by_key in sorted(variants.items()):
        entries = [_Merged(path, c, b, tuple(o)) for (c, b), o in by_key.items()]
        if len(entries) == 1:
            merged.append(entries[0])
        else:
            collided[path] = entries
    return merged, collided


def _current_bytes(root: Path, path: str) -> bytes | None:
    target = root / path
    return target.read_bytes() if target.is_file() and not target.is_symlink() else None


def _file_item(
    root: Path, manifest: OwnershipManifest, m: _Merged, risk: RiskRank
) -> tuple[SyncItem, bool]:
    """(item, 適用対象か)。"""
    change = PlannedChange(m.path, ChangeAction.UPDATE, m.content, "", "seh")
    status = classify_change(root, manifest, change)
    if status in _APPLICABLE:
        return SyncItem(m.path, status, m.content, m.owners, risk), True
    current = _current_bytes(root, m.path)
    diff = (
        None
        if current is None
        else render_three_way(ThreeWayDiff(m.path, None, current, m.content))
    )
    return SyncItem(m.path, status, m.content, m.owners, risk, diff), False


def _block_item(
    root: Path, manifest: OwnershipManifest, m: _Merged, risk: RiskRank
) -> tuple[SyncItem, bool]:
    block = m.content.decode("utf-8")
    probe = PlannedChange(m.path, ChangeAction.UPDATE, m.content, "", "seh")
    status = classify_change(root, manifest, probe)
    if status in (FileStatus.NEW, FileStatus.UNCHANGED, FileStatus.SYMLINK_CONFLICT):
        item = SyncItem(m.path, status, m.content, m.owners, risk, managed_block=True)
        return item, status is not FileStatus.SYMLINK_CONFLICT
    text = (root / m.path).read_text(encoding="utf-8")
    span = _block_span(text)
    if span is None:
        content = _insert_block(text, block).encode("utf-8")
        return SyncItem(m.path, "BLOCK_INSERT", content, m.owners, risk, managed_block=True), True
    current_block = text[span[0] : span[1]]
    content = (text[: span[0]] + block + text[span[1] :]).encode("utf-8")
    if current_block.rstrip("\n") == block.rstrip("\n"):
        return SyncItem(
            m.path, FileStatus.UNCHANGED, content, m.owners, risk, managed_block=True
        ), True
    entry = manifest.get(m.path)
    if entry is None:
        conflict: SyncStatus = FileStatus.USER_OWNED
    elif _sha256(current_block.encode("utf-8")) == entry.sha256:
        item = SyncItem(m.path, "BLOCK_UPDATE", content, m.owners, risk, managed_block=True)
        return item, True
    else:
        conflict = FileStatus.USER_MODIFIED
    diff = render_three_way(ThreeWayDiff(m.path, None, current_block.encode(), block.encode()))
    item = SyncItem(m.path, conflict, content, m.owners, risk, diff, managed_block=True)
    return item, False


def _collision_item(path: str, entries: list[_Merged]) -> SyncItem:
    owners = tuple(dict.fromkeys(o for e in entries for o in e.owners))
    return SyncItem(
        path,
        "CONTENT_COLLISION",
        entries[0].content,
        owners,
        classify_paths([path]),
        _unified(path, entries[0].content, entries[1].content),
    )


def _render_all(
    root: Path,
    hosts: Sequence[HostId],
    spec: CanonicalSpec,
    adapters: Mapping[HostId, HostAdapter],
) -> tuple[list[PlannedChange], list[Diagnostic], dict[HostId, tuple[HostCapability, ...]]]:
    ctx = RenderContext(root=root, enabled_hosts=tuple(hosts), project_name=root.resolve().name)
    changes: list[PlannedChange] = []
    diagnostics: list[Diagnostic] = []
    capabilities: dict[HostId, tuple[HostCapability, ...]] = {}
    for host in hosts:
        adapter = adapters[host]
        plan: GeneratedPlan = adapter.render(spec, ctx)
        changes += plan.changes
        diagnostics += [*plan.diagnostics, *adapter.lint(plan)]
        capabilities[host] = plan.capabilities
    return changes, diagnostics, capabilities


def plan_sync(
    root: Path,
    hosts: Sequence[HostId],
    *,
    spec: CanonicalSpec,
    adapters: Mapping[HostId, HostAdapter] | None = None,
) -> SyncPlan:
    changes, diagnostics, capabilities = _render_all(
        root, hosts, spec, adapters if adapters is not None else default_adapters()
    )
    merged, collided = _merge(changes)
    manifest = OwnershipManifest.load(root)
    items: list[SyncItem] = []
    conflicts: list[SyncItem] = [_collision_item(p, e) for p, e in collided.items()]
    collisions: list[str] = [f"PATH_CONTENT_COLLISION:{p}" for p in collided]
    for m in merged:
        risk = classify_paths([m.path])
        build = _block_item if m.is_block else _file_item
        try:
            item, applicable = build(root, manifest, m, risk)
        except (ValueError, UnicodeDecodeError) as error:
            diagnostics.append(
                Diagnostic(DiagnosticLevel.ERROR, "SYNC_UNSAFE_PATH", str(error), m.path)
            )
            continue
        (items if applicable else conflicts).append(item)
    seen = static_discovery(hosts, [m.path for m in merged], root)
    return SyncPlan(
        items=tuple(items),
        conflicts=tuple(conflicts),
        collisions=(*collisions, *discovery_collisions(seen)),
        diagnostics=tuple(diagnostics),
        capabilities=capabilities,
    )


# --- 適用 -------------------------------------------------------------------------


def _select_overwrites(plan: SyncPlan, overwrite: Collection[str]) -> list[SyncItem]:
    by_path = {c.path: c for c in plan.conflicts}
    chosen: list[SyncItem] = []
    for path in sorted(set(overwrite)):
        conflict = by_path.get(path)
        if conflict is None or conflict.status in _NOT_OVERWRITABLE:
            raise SyncError(f"overwrite できません（衝突として列挙されていないか不可）: {path}")
        chosen.append(conflict)
    return chosen


def _lock_document(
    plan: SyncPlan, seh_version: str, cli_versions: Mapping[str, str | None], files: int
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "seh_version": seh_version,
        "hosts": {
            host.value: {"cli": host.value, "version": cli_versions.get(host.value)}
            for host in plan.capabilities
        },
        "files": files,
    }


def apply_sync(
    root: Path,
    plan: SyncPlan,
    *,
    overwrite: Collection[str] = (),
    seh_version: str,
    cli_versions: Mapping[str, str | None],
) -> list[str]:
    recover_incomplete(root)
    overwritten = _select_overwrites(plan, overwrite)
    writes = [i for i in plan.items if i.status != FileStatus.UNCHANGED] + overwritten
    written: list[str] = []
    with Transaction(root) as tx:
        for item in writes:
            tx.write(item.path, item.content)
            written.append(item.path)
    manifest = OwnershipManifest.load(root)
    for item in [*plan.items, *overwritten]:
        if item in writes or manifest.get(item.path) is None:
            manifest.record(item.path, _recorded_sha(item), ",".join(item.owners), seh_version)
    manifest.save(root)
    lock = _lock_document(plan, seh_version, cli_versions, len(plan.items) + len(overwritten))
    atomic_write(root / LOCK_PATH, (json.dumps(lock, indent=2) + "\n").encode("utf-8"))
    return written
