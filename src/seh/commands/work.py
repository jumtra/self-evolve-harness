"""Managed ワークフローの起動と状態確認。"""

import argparse
import asyncio
import json
import sys
import uuid
from pathlib import Path

from seh.contracts.state import UnitState
from seh.runtime.checkpoint import CheckpointStore
from seh.runtime.gate import final_output_to_dict
from seh.runtime.managed import ManagedOptions, run_managed
from seh.runtime.runners.defaults import default_registry

REGISTRY = default_registry()


def _status(args: argparse.Namespace) -> int:
    checkpoint = CheckpointStore(Path(args.root), args.run_id).load()
    if checkpoint is None:
        print(f"run が見つかりません: {args.run_id}", file=sys.stderr)
        return 1
    if checkpoint.state.stopped_reason:
        print(checkpoint.state.stopped_reason)
    for node, state in checkpoint.state.states.items():
        print(f"{node}: {state.value} attempts={len(checkpoint.attempts.get(node, ()))}")
    return 0


def _run(args: argparse.Namespace) -> int:
    if args.mode == "native":
        print("native モードは各ホストの /work Skill から実行します")
        return 2
    return _execute(Path(args.root), Path(args.task), args.host, uuid.uuid4().hex, False)


def _resume(args: argparse.Namespace) -> int:
    checkpoint = CheckpointStore(Path(args.root), args.run_id).load()
    if checkpoint is None:
        print(f"run が見つかりません: {args.run_id}", file=sys.stderr)
        return 1
    task_file = checkpoint.task_summary.get("task_file")
    host = checkpoint.task_summary.get("host")
    if not isinstance(task_file, str) or not isinstance(host, str):
        print("再開情報がありません", file=sys.stderr)
        return 1
    return _execute(Path(args.root), Path(task_file), host, args.run_id, True)


def _execute(root: Path, task: Path, host: str, run_id: str, resume: bool) -> int:
    from seh.config import load_config

    try:
        config = load_config(root / ".harness" / "config.toml")
        runtime = config.runtime
        options = ManagedOptions(
            host,
            runtime.max_parallel,
            runtime.max_attempts_per_unit,
            runtime.max_seconds_per_unit,
            runtime.max_total_seconds,
            False,
        )
        result = asyncio.run(
            run_managed(root, task, options, runners=REGISTRY, run_id=run_id, resume=resume)
        )
    except (OSError, ValueError, KeyError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps({"run_id": run_id, **final_output_to_dict(result)}, ensure_ascii=False))
    return 0 if result.status is UnitState.PASSED else 1


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("work", help="ワークフローを実行")
    actions = parser.add_subparsers(dest="work_action")
    run = actions.add_parser("run")
    run.add_argument("--task", required=True)
    run.add_argument("--root", default=".")
    run.add_argument("--mode", choices=("native", "managed"), default="managed")
    run.add_argument("--host", default="claude")
    run.set_defaults(handler=_run)
    for action, handler in (("status", _status), ("resume", _resume)):
        sub = actions.add_parser(action)
        sub.add_argument("run_id")
        sub.add_argument("--root", default=".")
        sub.set_defaults(handler=handler)
