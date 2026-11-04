"""候補の作成・評価・昇格・復元。"""

import argparse
import asyncio
import json
import re
import subprocess
import sys
import tempfile
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from seh.contracts import ApprovalToken
from seh.evals.fixtures import DEFAULT_SUITE_ROOT, load_suite
from seh.evals.report import from_json, render_markdown, to_json
from seh.evals.variants import VARIANTS
from seh.evolution.benchmark import BenchmarkResult, benchmark, overlay_digest
from seh.evolution.propose import _check_path, _check_symlinks, propose
from seh.runtime.runners.defaults import default_registry
from seh.runtime.worktree import WorktreeError

REGISTRY = default_registry()


def _validate_id(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", value):
        raise ValueError("invalid candidate id")
    return value


def _read_changes(path: Path) -> dict[str, str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if (
        not isinstance(data, dict)
        or not data
        or not all(isinstance(k, str) and isinstance(v, str) for k, v in data.items())
    ):
        raise ValueError("changes must be a nonempty object of path to text")
    for key in data:
        _check_path(key)
    return data


def _metadata(root: Path, candidate_id: str) -> Path:
    return root / ".harness/state/evolution" / f"{_validate_id(candidate_id)}.json"


def _write_json(path: Path, data: object) -> None:
    from seh.ownership import atomic_write

    atomic_write(path, (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode())


def _load(root: Path, candidate_id: str) -> dict:
    data = json.loads(_metadata(root, candidate_id).read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("candidate_id") != candidate_id:
        raise ValueError("invalid candidate metadata")
    return data


def _snapshots(root: Path, data: dict) -> tuple[dict[str, bytes | None], dict[str, bytes | None]]:
    candidate_id = _validate_id(data["candidate_id"])
    run_id = _validate_id(data["run_id"])
    base = data["base"]
    if not isinstance(base, str) or not re.fullmatch(r"[0-9a-f]{40,64}", base):
        raise ValueError("invalid base commit")
    workspace = root / ".harness/state/worktrees" / run_id / candidate_id
    if not (workspace / ".git").is_file():
        raise ValueError("candidate worktree missing")
    baseline: dict[str, bytes | None] = {}
    candidate: dict[str, bytes | None] = {}
    for path in data["paths"]:
        _check_path(path)
        _check_symlinks(workspace, path)
        tree = subprocess.run(
            ["git", "-C", str(root), "ls-tree", "-z", base, "--", path],
            capture_output=True,
            check=True,
        ).stdout
        if tree:
            baseline[path] = subprocess.run(
                ["git", "-C", str(root), "show", f"{base}:{path}"], capture_output=True, check=True
            ).stdout
        else:
            baseline[path] = None
        target = workspace / path
        candidate[path] = target.read_bytes() if target.is_file() else None
    if not candidate:
        raise ValueError("candidate has no changes")
    return baseline, candidate


def _source_evidence(root: Path, run_id: str) -> list[str]:
    attempts = root / ".harness/state/runs" / run_id / "attempts"
    refs: list[str] = []
    for path in sorted(attempts.glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError("SOURCE_EVIDENCE_INVALID")
            failed = row.get("verdict_status") in {"FAIL", "FAILED"} or row.get(
                "terminal_state"
            ) in {"FAIL", "FAILED"}
            if failed and isinstance(row.get("reason_code"), str) and row["reason_code"]:
                refs.append(f"attempt:{run_id}:{path.stem}:{row.get('attempt', 0)}")
    if not refs:
        raise ValueError("SOURCE_EVIDENCE_MISSING: no recorded failure for run")
    return refs


def _propose(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    candidate_id = _validate_id(args.id or uuid.uuid4().hex)
    run_id = _validate_id(args.source)
    evidence_refs = _source_evidence(root, run_id)
    if _metadata(root, candidate_id).exists():
        raise ValueError("candidate already exists")
    candidate = asyncio.run(
        propose(
            root,
            run_id=run_id,
            candidate_id=candidate_id,
            changes=_read_changes(Path(args.changes)),
        )
    )
    _write_json(
        _metadata(root, candidate_id),
        {
            "candidate_id": candidate_id,
            "run_id": run_id,
            "base": candidate.workspace.base_commit,
            "paths": candidate.changed_paths,
            "evidence_refs": evidence_refs,
            "status": "proposed",
            "generated": False,
            "updated_at": datetime.now(UTC).isoformat(),
        },
    )
    print(f"candidate: {candidate_id}")
    return 0


def _benchmark(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    data = _load(root, args.candidate)
    if data.get("status") == "retired":
        raise ValueError("CANDIDATE_RETIRED")
    before, after = _snapshots(root, data)
    if args.host == "antigravity":
        raise ValueError("POLICY_BLOCKED: antigravity cannot run eval")
    runner = REGISTRY.get(args.host)
    suite = Path(args.suite) if args.suite else root / DEFAULT_SUITE_ROOT
    cases = load_suite(suite if suite.is_absolute() else root / suite)
    with tempfile.TemporaryDirectory(prefix="seh-evolution-") as directory:
        result = asyncio.run(
            benchmark(
                cases,
                VARIANTS["V0"],
                runner,
                trials=args.trials,
                workroot=Path(directory),
                baseline_files=before,
                candidate_files=after,
            )
        )
    data["benchmark"] = {
        "baseline": json.loads(to_json(result.baseline)),
        "candidate": json.loads(to_json(result.candidate)),
        "baseline_digest": result.baseline_digest,
        "candidate_digest": result.candidate_digest,
    }
    data["updated_at"] = datetime.now(UTC).isoformat()
    _write_json(_metadata(root, args.candidate), data)
    print(render_markdown([result.baseline, result.candidate], result.comparison))
    return 0 if result.comparison.promotable else 1


def _promote(args: argparse.Namespace) -> int:
    from seh.evals.report import compare
    from seh.evolution.promote import promote

    root = Path(args.root).resolve()
    data = _load(root, args.candidate)
    if data.get("status") == "retired":
        raise ValueError("CANDIDATE_RETIRED")
    _, files = _snapshots(root, data)
    info = data["benchmark"]
    baseline = from_json(json.dumps(info["baseline"]))
    candidate = from_json(json.dumps(info["candidate"]))
    evidence = BenchmarkResult(
        baseline,
        candidate,
        compare(baseline, candidate),
        info["baseline_digest"],
        info["candidate_digest"],
    )
    if not sys.stdin.isatty():
        raise ValueError("human approval requires an interactive terminal")
    print(
        f"candidate: {args.candidate}; files: {', '.join(files)}; digest: {overlay_digest(files)}"
    )
    if input("昇格を承認しますか? [y/N] ").strip().lower() != "y":
        raise ValueError("approval denied")
    now = datetime.now(UTC)
    token = ApprovalToken(
        uuid.uuid4().hex,
        (f"evolve:promote:{args.candidate}",),
        overlay_digest(files),
        now + timedelta(minutes=5),
        "human",
    )
    snapshot = promote(
        root, args.candidate, files, evidence, approval=token, now=now, authoring_record=args.record
    )
    data["status"] = "promoted"
    data["updated_at"] = now.isoformat()
    data["promotion"] = snapshot
    _write_json(_metadata(root, args.candidate), data)
    print(f"promotion: {snapshot}")
    return 0


def _rollback(args: argparse.Namespace) -> int:
    from seh.evolution.rollback import rollback_promotion

    for path in rollback_promotion(Path(args.root), args.promotion):
        print(f"restored: {path}")
    return 0


def _retire(args: argparse.Namespace) -> int:
    from seh.evolution.lifecycle import CandidateRecord, retire_stale

    if args.days <= 0:
        raise ValueError("days must be positive")
    root = Path(args.root).resolve()
    directory = root / ".harness/state/evolution"
    now = datetime.now(UTC)
    for path in sorted(directory.glob("*.json")):
        if path.is_symlink():
            raise ValueError(f"symlink candidate metadata: {path.name}")
        data = _load(root, path.stem)
        # Older records lack provenance and age, so do not automatically retire them.
        if data.get("generated") is not True or not isinstance(data.get("updated_at"), str):
            continue
        status = data.get("status")
        if status not in {"proposed", "failed", "stalled", "promoted", "retired"}:
            raise ValueError(f"invalid candidate status: {path.name}")
        updated = datetime.fromisoformat(data["updated_at"])
        if updated.tzinfo is None:
            raise ValueError(f"missing timezone: {path.name}")
        record = CandidateRecord(path.stem, status, updated, True)
        retired = retire_stale([record], now=now, max_age=timedelta(days=args.days))[0]
        if retired.status != record.status:
            data["status"] = retired.status
            data["updated_at"] = now.isoformat()
            _write_json(path, data)
            print(f"retired: {path.stem}")
    return 0


def _learn(args: argparse.Namespace) -> int:
    from seh.evolution.learning import record_learning

    constraint = record_learning(
        Path(args.root).resolve(),
        id=args.id,
        statement=args.statement,
        scope_globs=tuple(args.scope),
        source_record=args.promotion,
        evidence_refs=tuple(args.evidence),
        now=datetime.now(UTC),
    )
    print(f"learning: {constraint.id}")
    return 0


def _handle(args: argparse.Namespace) -> int:
    try:
        return args.action_handler(args)
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        subprocess.SubprocessError,
        WorktreeError,
    ) as exc:
        print(f"evolve: {exc}", file=sys.stderr)
        return 1


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("evolve", help="候補の作成・評価・昇格")
    sub = parser.add_subparsers(dest="evolve_action", required=True)
    proposal = sub.add_parser("propose")
    proposal.add_argument("--root", default=".")
    proposal.add_argument("--from", dest="source", required=True)
    proposal.add_argument("--changes", required=True, help="path と変更内容の JSON")
    proposal.add_argument("--id")
    proposal.set_defaults(handler=_handle, action_handler=_propose)
    bench = sub.add_parser("benchmark")
    bench.add_argument("candidate")
    bench.add_argument("--root", default=".")
    bench.add_argument("--suite")
    bench.add_argument("--host", default="claude")
    bench.add_argument("--trials", type=int, default=1)
    bench.set_defaults(handler=_handle, action_handler=_benchmark)
    prom = sub.add_parser("promote")
    prom.add_argument("candidate")
    prom.add_argument("--root", default=".")
    prom.add_argument("--record")
    prom.set_defaults(handler=_handle, action_handler=_promote)
    back = sub.add_parser("rollback")
    back.add_argument("promotion")
    back.add_argument("--root", default=".")
    back.set_defaults(handler=_handle, action_handler=_rollback)
    retire = sub.add_parser("retire")
    retire.add_argument("--root", default=".")
    retire.add_argument("--days", type=int, default=30)
    retire.set_defaults(handler=_handle, action_handler=_retire)
    learn = sub.add_parser("learn")
    learn.add_argument("--root", default=".")
    learn.add_argument("--promotion", required=True)
    learn.add_argument("--id", required=True)
    learn.add_argument("--statement", required=True)
    learn.add_argument("--scope", action="append", required=True)
    learn.add_argument("--evidence", action="append", required=True)
    learn.set_defaults(handler=_handle, action_handler=_learn)
