# ハンドラ契約: handler(args: argparse.Namespace) -> int（戻り値が終了コード）。
import argparse
import json
import sys
from pathlib import Path

from seh.registry import ModuleRegistry, RegistryError, discover_manifests


def _handle(args: argparse.Namespace) -> int:
    print("未実装: seh module（サブコマンドを指定してください: list / enable）", file=sys.stderr)
    return 2


def _extra_dirs(args: argparse.Namespace) -> list[Path]:
    return [Path(d) for d in args.extra_dir]


def _list(args: argparse.Namespace) -> int:
    try:
        manifests = discover_manifests(extra_dirs=_extra_dirs(args))
    except RegistryError as exc:
        print(f"エラー: {exc}", file=sys.stderr)
        return 1
    if args.format == "json":
        rows = [
            {
                "id": m.id,
                "version": m.version,
                "provides": list(m.provides),
                "default_enabled": m.default_enabled,
                "opt_in": m.opt_in,
            }
            for m in manifests
        ]
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return 0
    for m in manifests:
        print(
            f"{m.id}  v{m.version}  provides={','.join(m.provides)}  "
            f"default_enabled={str(m.default_enabled).lower()}  opt_in={str(m.opt_in).lower()}"
        )
    return 0


def _enable(args: argparse.Namespace) -> int:
    if args.apply:
        print(
            "--apply は未対応です。設定変更は `seh config set` / `seh init` で行ってください。",
            file=sys.stderr,
        )
        return 2
    if not args.plan:
        print("--plan を指定してください（書き込みは行いません）。", file=sys.stderr)
        return 2
    try:
        registry = ModuleRegistry(discover_manifests(extra_dirs=_extra_dirs(args)))
    except RegistryError as exc:
        print(f"エラー: {exc}", file=sys.stderr)
        return 1
    plan = registry.resolve([args.id, *args.with_ids])
    if plan.errors:
        print("解決エラー:")
        for error in plan.errors:
            print(f"  {error}")
        return 1
    print("有効化されるモジュール（依存順）:")
    for module_id in plan.enabled:
        print(f"  {module_id}")
    print("Capability 台帳:")
    for capability, module_id in sorted(plan.capabilities.items()):
        print(f"  {capability} <- {module_id}")
    return 0


def register(subparsers: "argparse._SubParsersAction[argparse.ArgumentParser]") -> None:
    parser = subparsers.add_parser("module", help="モジュールの一覧と有効化計画")
    parser.set_defaults(handler=_handle)
    sub = parser.add_subparsers(dest="module_command", metavar="<subcommand>")

    list_parser = sub.add_parser("list", help="モジュール一覧")
    list_parser.add_argument("--format", choices=("text", "json"), default="text")
    list_parser.add_argument("--extra-dir", action="append", default=[], metavar="DIR")
    list_parser.set_defaults(handler=_list)

    enable_parser = sub.add_parser("enable", help="モジュール有効化の計画")
    enable_parser.add_argument("id")
    enable_parser.add_argument("--with", dest="with_ids", action="append", default=[], metavar="ID")
    enable_parser.add_argument("--extra-dir", action="append", default=[], metavar="DIR")
    enable_parser.add_argument("--plan", action="store_true")
    enable_parser.add_argument("--apply", action="store_true")
    enable_parser.set_defaults(handler=_enable)
