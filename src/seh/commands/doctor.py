# ハンドラ契約: handler(args: argparse.Namespace) -> int（戻り値が終了コード）。
import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from seh.compatibility import build_report
from seh.contracts import DiagnosticLevel, HostId
from seh.doctor import DoctorContext, Finding, run_doctor


def _format_text(findings: list[Finding]) -> str:
    return "\n".join(f"[{f.level}] {f.check}: {f.code} — {f.message}" for f in findings)


def _handle(args: argparse.Namespace) -> int:
    if args.output and not args.hosts:
        print("--output requires --hosts", file=sys.stderr)
        return 1
    ctx = DoctorContext(root=Path(args.root), options={"context": args.context})
    findings = run_doctor(ctx)
    report = None
    if args.hosts:
        try:
            hosts = (
                list(HostId)
                if args.hosts == "all"
                else [HostId(h.strip()) for h in args.hosts.split(",")]
            )
        except ValueError as exc:
            print(f"invalid host: {exc}", file=sys.stderr)
            return 1
        report = build_report(ctx.root, hosts)
        if args.output:
            Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    if args.format == "json":
        output = (
            {"findings": [asdict(f) for f in findings], "compatibility": report}
            if report
            else [asdict(f) for f in findings]
        )
        print(json.dumps(output, ensure_ascii=False, indent=2))
    elif findings:
        print(_format_text(findings))
    else:
        print("問題は見つかりませんでした")
    if report and args.format == "text":
        print(json.dumps(report, ensure_ascii=False, indent=2))
    blocked = report and any(h["verdict"] == "BLOCKED" for h in report["hosts"].values())
    return 1 if blocked or any(f.level is DiagnosticLevel.ERROR for f in findings) else 0


def register(subparsers: "argparse._SubParsersAction[argparse.ArgumentParser]") -> None:
    parser = subparsers.add_parser("doctor", help="オフラインで設定・モジュール状態を診断する")
    parser.add_argument("--root", default=".", help="対象リポジトリのルート")
    parser.add_argument("--format", choices=("text", "json"), default="text")
    parser.add_argument("--context", action="store_true", help="常時 Context の大きさを計測する")
    parser.add_argument("--hosts", help="all またはカンマ区切りのホスト名")
    parser.add_argument("--output", help="互換性 JSON の出力先（--hosts と併用）")
    parser.set_defaults(handler=_handle)
