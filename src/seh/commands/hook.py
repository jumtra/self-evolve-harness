# ハンドラ契約: handler(args: argparse.Namespace) -> int（戻り値が終了コード）。
import argparse
import sys
from pathlib import Path

from seh.contracts import HostId
from seh.events import run_hook
from seh.policy import Policy
from seh.trace import TraceWriter


def _handle(args: argparse.Namespace) -> int:
    root = Path(args.root)
    harness_dir = root / ".harness"
    trace = (
        TraceWriter(harness_dir / "state" / "hook-trace.jsonl") if harness_dir.is_dir() else None
    )
    payload = sys.stdin.buffer.read()
    code, stdout, stderr = run_hook(
        args.event, HostId(args.host), payload, policy=Policy(), trace=trace
    )
    if stdout:
        sys.stdout.write(stdout)
    if stderr:
        sys.stderr.write(stderr)
    return code


def register(subparsers: "argparse._SubParsersAction[argparse.ArgumentParser]") -> None:
    parser = subparsers.add_parser("hook", help="ホストの Hook から呼ばれる単一入口")
    parser.add_argument("event")
    parser.add_argument("--host", choices=[h.value for h in HostId], default=HostId.CLAUDE.value)
    parser.add_argument("--root", default=".")
    parser.set_defaults(handler=_handle)
