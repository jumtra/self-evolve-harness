"""Managed の状態遷移と Native の未評価変更の検出。"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

from seh.authoring.classify import FileChange, changes_from_git, classify_change, classify_changes
from seh.authoring.promote import load_records
from seh.contracts import AuthoringRecord, AuthoringRisk, AuthoringState, transition_authoring
from seh.globs import match_path
from seh.ownership import atomic_write

MAX_STOP_BLOCKS = 2
_RUN_ID = re.compile(r"[A-Za-z0-9_-]+")


def target_digests(root: Path, paths: tuple[str, ...]) -> dict[str, str]:
    root = root.resolve()
    digests: dict[str, str] = {}
    for rel in paths:
        path = Path(rel)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("unsafe authoring target")
        target = root / path
        if target.resolve() != target:
            raise ValueError("authoring target contains a symlink")
        if target.exists() and not target.is_file():
            raise ValueError("authoring target is not a file")
        digests[f"target:{rel}"] = (
            hashlib.sha256(target.read_bytes()).hexdigest() if target.is_file() else "MISSING"
        )
    return digests


def _has_baseline(root: Path, record: AuthoringRecord) -> bool:
    run_id = record.baseline_run_id
    if not run_id or not _RUN_ID.fullmatch(run_id):
        return False
    from seh.evals.report import from_json

    path = root / ".harness/authoring/evals" / f"{run_id}.json"
    try:
        if not path.resolve().is_relative_to(root.resolve()):
            return False
        run = from_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, KeyError, TypeError):
        return False
    try:
        targets = target_digests(root, record.target_paths)
    except (OSError, ValueError):
        return False
    return (
        run.run_id == run_id
        and bool(run.trials)
        and bool(targets)
        and all(run.components.get(key) == value for key, value in targets.items())
    )


def advance(record: AuthoringRecord, state: AuthoringState) -> AuthoringRecord:
    if state is AuthoringState.APPROVED and not record.approval_ref:
        raise ValueError("approval evidence required")
    if state is AuthoringState.BASELINED and not record.baseline_run_id:
        raise ValueError("baseline evaluation required")
    if state is AuthoringState.COMPARED and not record.candidate_run_id:
        raise ValueError("candidate evaluation required")
    return transition_authoring(record, state)


def write_requires_plan(root: Path, paths: tuple[str, ...]) -> bool:
    for path in paths:
        candidate = Path(path)
        if candidate.is_absolute():
            try:
                candidate = candidate.relative_to(root.resolve())
            except ValueError:
                return True
        path = candidate.as_posix().lower()
        if ".." in candidate.parts:
            return True
        if any(char in path for char in "*?["):
            first = path.split("/", 1)[0]
            # A wildcard in the first component could select any protected root.
            # Under a protected root, do not guess from a few sample filenames.
            if any(char in first for char in "*?[") or first in {
                ".claude",
                ".agents",
                ".codex",
                ".opencode",
                ".harness",
            }:
                return True
            # Nested instruction files are protected in otherwise ordinary directories.
            if any(match_path(name, candidate.name.lower()) for name in ("claude.md", "agents.md")):
                return True
            continue
        result = classify_change(FileChange(candidate.as_posix(), None, "proposed change"))
        if result and result.risk is not AuthoringRisk.TEXT_ONLY:
            return True
    return False


def write_is_authorized(root: Path, paths: tuple[str, ...]) -> bool:
    records = load_records(root)
    for path in paths:
        candidate = Path(path)
        if candidate.is_absolute():
            try:
                candidate = candidate.relative_to(root.resolve())
            except ValueError:
                return False
        rel = candidate.as_posix()
        if not write_requires_plan(root, (rel,)):
            continue
        if not any(
            rel in record.target_paths
            and record.state is AuthoringState.BASELINED
            and _has_baseline(root, record)
            and (record.risk is not AuthoringRisk.HIGH_RISK or record.approval_ref)
            for record in records
        ):
            return False
    return True


@dataclass(frozen=True)
class NativeStop:
    needs_eval: bool
    block: bool
    paths: tuple[str, ...]


def _reviewed_paths(root: Path) -> set[str]:
    # Gate の評価済み候補ハッシュと現在の正本が一致する場合のみ評価済みとする。
    from seh.authoring.gate import GateStatus
    from seh.commands.author import _gate, _load_eval_run
    from seh.config import ConfigError, load_config

    try:
        config = load_config(root / ".harness/config.toml")
        records = load_records(root)
    except (OSError, ValueError, ConfigError):
        return set()
    reviewed: set[str] = set()
    for record in records:
        candidate = _load_eval_run(root, record.candidate_run_id)
        if candidate is None or _gate(root, config, record, None).status is not GateStatus.PASS:
            continue
        for path in record.target_paths:
            prefix = ".harness/spec/"
            if not path.startswith(prefix):
                continue
            target = root / path
            if not target.is_file() or target.is_symlink():
                continue
            digest = hashlib.sha256(target.read_bytes()).hexdigest()
            if candidate.components.get("file:" + path.removeprefix(prefix)) == digest:
                reviewed.add(path)
    return reviewed


def native_stop(root: Path, session_id: str) -> NativeStop:
    changes = classify_changes(changes_from_git(root, "HEAD", None))
    reviewed = _reviewed_paths(root)
    paths = tuple(
        sorted(
            c.path
            for c in changes
            if c.risk is not AuthoringRisk.TEXT_ONLY and c.path not in reviewed
        )
    )
    if not paths:
        return NativeStop(False, False, ())
    key = hashlib.sha256(session_id.encode()).hexdigest()
    state_path = root / ".harness/state/authoring-stop" / f"{key}.json"
    count = 0
    if state_path.is_file():
        data = json.loads(state_path.read_text(encoding="utf-8"))
        if data.get("paths") == list(paths):
            count = int(data["count"])
    count += 1
    atomic_write(
        state_path, json.dumps({"state": "NEEDS_EVAL", "paths": paths, "count": count}).encode()
    )
    return NativeStop(True, count <= MAX_STOP_BLOCKS, paths)
