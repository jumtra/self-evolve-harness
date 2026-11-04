# ハンドラ契約: handler(args: argparse.Namespace) -> int（戻り値が終了コード）。
import argparse
import os
import sys
from pathlib import Path

from seh.contracts import HostId
from seh.events import KNOWN_EVENTS, HookDecision, HookOutcome, render_outcome, run_hook
from seh.policy import Policy
from seh.trace import TraceWriter


def _emit(code: int, stdout: str, stderr: str) -> int:
    if stdout:
        sys.stdout.write(stdout)
    if stderr:
        sys.stderr.write(stderr)
    return code


def _run(args: argparse.Namespace) -> int:
    root = Path(args.root)
    harness_dir = root / ".harness"
    trace = (
        TraceWriter(harness_dir / "state" / "hook-trace.jsonl") if harness_dir.is_dir() else None
    )
    payload = sys.stdin.buffer.read()
    unattended = bool(args.unattended) or os.environ.get("SEH_UNATTENDED") == "1"
    return _emit(
        *run_hook(
            args.event,
            HostId(args.host),
            payload,
            policy=Policy(),
            trace=trace,
            unattended=unattended,
        )
    )


def _handle(args: argparse.Namespace) -> int:
    # run_hook の外（stdin 読込・Policy 生成など）の失敗も、Claude では exit 1 だと非ブロックになる
    try:
        return _run(args)
    except Exception as e:  # fail-closed のため意図的に全例外を捕捉する
        if args.event in KNOWN_EVENTS and args.event != "PreToolUse":
            return _emit(0, "", f"警告: Hook 内部エラー: {type(e).__name__}")
        outcome = HookOutcome(
            HookDecision.DENY, "INTERNAL_ERROR", f"Hook 内部エラー: {type(e).__name__}"
        )
        return _emit(*render_outcome(outcome, HostId(args.host)))


def register(subparsers: "argparse._SubParsersAction[argparse.ArgumentParser]") -> None:
    parser = subparsers.add_parser("hook", help="ホストの Hook から呼ばれる単一入口")
    parser.add_argument("event")
    parser.add_argument("--host", choices=[h.value for h in HostId], default=HostId.CLAUDE.value)
    parser.add_argument("--root", default=".")
    parser.add_argument("--unattended", action="store_true")
    parser.set_defaults(handler=_handle)
