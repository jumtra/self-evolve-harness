# ハンドラ契約: handler(args: argparse.Namespace) -> int（戻り値が終了コード）。
import argparse
import json
import sys
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path

from seh import __version__
from seh.commands.sync import _cli_versions as _probe_cli_versions
from seh.config import ConfigError
from seh.contracts import DiagnosticLevel, HostId
from seh.doctor import DoctorContext, run_doctor
from seh.init.apply import apply_init
from seh.init.detect import ci_check_cmd, ci_fix_cmd
from seh.init.planner import InitError, InitOptions, InitPlan, plan_init
from seh.migration.apply import PlanInvalid, PlanStale
from seh.spec_loader import SpecError
from seh.sync import SyncError, SyncItem, default_adapters


def _parse_hosts(raw: str | None) -> tuple[HostId, ...] | None:
    if raw is None:
        return None
    if raw == "all":
        return tuple(HostId)
    return tuple(HostId(name.strip()) for name in raw.split(",") if name.strip())


def _cli_versions(hosts: Sequence[HostId]) -> dict[str, str | None]:
    return _probe_cli_versions(default_adapters(), hosts)


def _item_dict(item: SyncItem) -> dict[str, object]:
    return {
        "path": item.path,
        "status": str(item.status),
        "risk": item.risk.value,
        "owners": list(item.owners),
        "diff": item.diff,
    }


def _plan_dict(plan: InitPlan) -> dict[str, object]:
    return {
        "detection": asdict(plan.detection),
        "config_toml": plan.config_toml,
        "spec_files": sorted(plan.spec_files),
        "migration": [
            {"path": i.path, "action": i.action.value, "reason": i.reason}
            for i in (plan.migration.items if plan.migration else ())
        ],
        "sync": {
            "items": [_item_dict(i) for i in plan.sync.items],
            "conflicts": [_item_dict(i) for i in plan.sync.conflicts],
            "collisions": list(plan.sync.collisions),
            "diagnostics": [{**asdict(d), "level": d.level.value} for d in plan.sync.diagnostics],
        },
        "gitignore_block": plan.gitignore_block,
    }


def _format_text(plan: InitPlan) -> str:
    lines = ["== 検出 =="]
    for app in plan.detection.root_apps:
        lines.append(f"  {app.path}: {', '.join(app.languages)} / {app.task_runner or '-'}")
        lines.append(f"    CI_CHECK_CMD: {ci_check_cmd(app) or '未検出'}")
        lines.append(f"    CI_FIX_CMD: {ci_fix_cmd(app) or '未検出'}")
    if not plan.detection.root_apps:
        lines.append("  アプリを検出できませんでした")
    lines += ["", "== .harness/config.toml ==", plan.config_toml.rstrip("\n")]
    lines += ["", f"== 正本 spec（{len(plan.spec_files)} 件） =="]
    lines += [f"  {path}" for path in sorted(plan.spec_files)]
    if plan.migration is not None:
        lines += ["", "== v1 移行 =="]
        lines += [f"  [{i.action}] {i.path} — {i.reason}" for i in plan.migration.items]
    sync = plan.sync
    lines += ["", f"== sync: 変更 {len(sync.items)} 件 / 衝突 {len(sync.conflicts)} 件 =="]
    lines += [f"  {i.status} {i.risk.value} {i.path} ({', '.join(i.owners)})" for i in sync.items]
    for conflict in sync.conflicts:
        lines.append(f"  [CONFLICT] {conflict.status} {conflict.path}")
        if conflict.diff:
            lines.append(conflict.diff.rstrip("\n"))
    lines += [f"  [COLLISION] {c}" for c in sync.collisions]
    lines += [f"  [{d.level}] {d.code}: {d.message}" for d in sync.diagnostics]
    return "\n".join(lines)


def _blocked(plan: InitPlan) -> bool:
    return any(d.level is DiagnosticLevel.ERROR for d in plan.sync.diagnostics) or any(
        c.status == "CONTENT_COLLISION" for c in plan.sync.conflicts
    )


def _confirm() -> bool:
    if not sys.stdin.isatty():
        print("承認が必要です。対話モードで再実行してください", file=sys.stderr)
        return False
    return input("適用しますか? [y/N] ").strip().lower() == "y"


def _show(plan: InitPlan, fmt: str) -> None:
    if fmt == "json":
        print(json.dumps(_plan_dict(plan), ensure_ascii=False, indent=2))
    else:
        print(_format_text(plan))


def _apply(root: Path, plan: InitPlan, approve: list[str]) -> int:
    if _blocked(plan):
        print("ERROR または内容衝突があるため適用しません", file=sys.stderr)
        return 1
    if not _confirm():
        return 1
    hosts = plan.config.hosts.enabled
    result = apply_init(
        root,
        plan,
        approve_conflicts=approve,
        seh_version=__version__,
        cli_versions=_cli_versions(hosts),
    )
    findings = run_doctor(DoctorContext(root=root, options={"context": False}))
    errors = sum(f.level is DiagnosticLevel.ERROR for f in findings)
    warns = sum(f.level is DiagnosticLevel.WARN for f in findings)
    print(f"導入しました。書込: {len(result.written)} 件")
    print(f"doctor: ERROR {errors} 件 / WARN {warns} 件")
    for finding in findings:
        if finding.level is not DiagnosticLevel.INFO:
            print(f"  [{finding.level}] {finding.check}: {finding.code} — {finding.message}")
    if result.migration_snapshot:
        print(f"snapshot: {result.migration_snapshot}")
        print(f"元に戻す: seh migrate rollback {result.migration_snapshot} --root {root}")
    else:
        print("v1 移行はありませんでした（元に戻す対象の移行 snapshot なし）")
    return 0


def _handle(args: argparse.Namespace) -> int:
    root = Path(args.root)
    try:
        options = InitOptions(
            profile=args.profile,
            hosts=_parse_hosts(args.hosts),
            code_intelligence=args.code_intel,
            memory=args.memory,
        )
        plan = plan_init(root, options)
        _show(plan, args.format)
        if args.apply:
            return _apply(root, plan, list(args.approve_conflict))
    except (InitError, ConfigError, SpecError, SyncError, PlanStale, PlanInvalid, ValueError) as e:
        notes = "".join(f"\n{n}" for n in getattr(e, "__notes__", []))
        print(f"{e}{notes}", file=sys.stderr)
        return 1
    return 1 if _blocked(plan) else 0


def register(subparsers: "argparse._SubParsersAction[argparse.ArgumentParser]") -> None:
    parser = subparsers.add_parser("init", help="対象リポジトリに v2 ハーネスを導入する")
    parser.add_argument("--root", default=".", help="対象リポジトリのルート")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--plan", action="store_true", help="導入計画を表示する（書込なし）")
    mode.add_argument("--apply", action="store_true", help="承認後に導入する")
    parser.add_argument("--profile", choices=("minimal", "balanced", "full"), default="balanced")
    parser.add_argument(
        "--hosts", default=None, help="all または claude,antigravity,codex,opencode"
    )
    parser.add_argument("--code-intel", choices=("codegraph", "graphify", "none"), default=None)
    parser.add_argument("--memory", choices=("file", "engram"), default=None)
    parser.add_argument(
        "--approve-conflict", nargs="+", action="extend", default=[], metavar="PATH"
    )
    parser.add_argument("--format", choices=("text", "json"), default="text")
    parser.set_defaults(handler=_handle)
