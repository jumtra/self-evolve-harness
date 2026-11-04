# ハンドラ契約: handler(args: argparse.Namespace) -> int（戻り値が終了コード）。
import argparse
import json
import sys
from pathlib import Path

from seh.migration.apply import PlanInvalid, PlanStale, apply_migration
from seh.migration.inventory import detect_v1
from seh.migration.planner import (
    MigrationPlan,
    load_plan,
    plan_migration,
    plan_to_dict,
    save_plan,
)
from seh.migration.rollback import rollback_migration


def _format_plan(plan: MigrationPlan) -> str:
    lines = [f"移行計画 {plan.plan_id}（baseline: {plan.baseline_ref}）"]
    for item in plan.items:
        lines.append(f"[{item.action}] {item.path} — {item.reason}")
        if item.diff:
            lines.extend(f"    {line}" for line in item.diff.splitlines())
    return "\n".join(lines)


def _plan(args: argparse.Namespace) -> int:
    root = Path(args.root)
    if not detect_v1(root):
        print("v1 ハーネスは見つかりません")
        return 0
    plan = plan_migration(root)
    saved = save_plan(root, plan)
    if args.format == "json":
        print(json.dumps(plan_to_dict(plan), ensure_ascii=False, indent=2))
    else:
        print(_format_plan(plan))
        print(f"計画を保存しました: {saved}")
    return 0


def _confirm() -> bool:
    if not sys.stdin.isatty():
        print("承認が必要です。対話モードで再実行してください", file=sys.stderr)
        return False
    print("適用しますか? [y/N] ", end="", flush=True)
    return sys.stdin.readline().strip() == "y"


def _apply(args: argparse.Namespace) -> int:
    root = Path(args.root)
    try:
        plan = load_plan(Path(args.plan))
    except (OSError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 1
    print(_format_plan(plan))
    if not _confirm():
        return 1
    try:
        result = apply_migration(root, plan, approve_conflicts=args.approve_conflict)
    except (PlanStale, PlanInvalid, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 1
    print(f"適用しました。削除: {len(result.deleted)} 件 / 保留: {len(result.skipped)} 件")
    for path in result.skipped:
        print(f"  保留（未承認の競合）: {path}")
    print(f"snapshot: {result.snapshot_id}")
    print(f"元に戻す: seh migrate rollback {result.snapshot_id} --root {root}")
    return 0


def _rollback(args: argparse.Namespace) -> int:
    try:
        restored = rollback_migration(Path(args.root), args.snapshot_id)
    except (OSError, ValueError, KeyError) as error:
        print(f"rollback に失敗しました: {error}", file=sys.stderr)
        return 1
    for path in restored:
        print(f"復元: {path}")
    print(f"{len(restored)} 件を復元しました")
    return 0


def _handle(args: argparse.Namespace) -> int:
    args.migrate_parser.print_help()
    return 2


def register(subparsers: "argparse._SubParsersAction[argparse.ArgumentParser]") -> None:
    parser = subparsers.add_parser("migrate", help="v1 ハーネスを v2 へ移行する")
    parser.set_defaults(handler=_handle, migrate_parser=parser)
    sub = parser.add_subparsers(dest="migrate_command", metavar="<action>")

    plan = sub.add_parser("plan", help="移行計画を作成して表示・保存する（read-only）")
    plan.add_argument("--root", default=".", help="対象リポジトリのルート")
    plan.add_argument("--from", dest="source", choices=("v1",), default="v1")
    plan.add_argument("--format", choices=("text", "json"), default="text")
    plan.set_defaults(handler=_plan)

    apply = sub.add_parser("apply", help="承認後に計画を原子的に適用する")
    apply.add_argument("--plan", required=True, help="seh migrate plan が保存した計画ファイル")
    apply.add_argument("--root", default=".", help="対象リポジトリのルート")
    apply.add_argument(
        "--approve-conflict",
        action="append",
        default=[],
        metavar="PATH",
        help="USER_OWNED_CONFLICT の置換を承認するパス（複数指定可）",
    )
    apply.set_defaults(handler=_apply)

    rollback = sub.add_parser("rollback", help="snapshot から適用前の状態へ戻す")
    rollback.add_argument("snapshot_id")
    rollback.add_argument("--root", default=".", help="対象リポジトリのルート")
    rollback.set_defaults(handler=_rollback)
