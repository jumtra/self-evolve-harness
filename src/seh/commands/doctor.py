# ハンドラ契約: handler(args: argparse.Namespace) -> int（戻り値が終了コード）。
import argparse
import json
from dataclasses import asdict
from pathlib import Path

from seh.contracts import DiagnosticLevel
from seh.doctor import DoctorContext, Finding, run_doctor


def _format_text(findings: list[Finding]) -> str:
    return "\n".join(f"[{f.level}] {f.check}: {f.code} — {f.message}" for f in findings)


def _handle(args: argparse.Namespace) -> int:
    ctx = DoctorContext(root=Path(args.root), options={"context": args.context})
    findings = run_doctor(ctx)
    if args.format == "json":
        print(json.dumps([asdict(f) for f in findings], ensure_ascii=False, indent=2))
    elif findings:
        print(_format_text(findings))
    else:
        print("問題は見つかりませんでした")
    return 1 if any(f.level is DiagnosticLevel.ERROR for f in findings) else 0


def register(subparsers: "argparse._SubParsersAction[argparse.ArgumentParser]") -> None:
    parser = subparsers.add_parser("doctor", help="オフラインで設定・モジュール状態を診断する")
    parser.add_argument("--root", default=".", help="対象リポジトリのルート")
    parser.add_argument("--format", choices=("text", "json"), default="text")
    parser.add_argument("--context", action="store_true", help="常時 Context の大きさを計測する")
    parser.set_defaults(handler=_handle)
