# ハンドラ契約: handler(args: argparse.Namespace) -> int（戻り値が終了コード）。
import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from pathlib import Path

from seh import __version__
from seh.config import ConfigError, load_config
from seh.contracts import DiagnosticLevel, HostAdapter, HostId, RiskRank
from seh.spec_loader import SpecError, load_spec
from seh.sync import SyncError, SyncItem, SyncPlan, apply_sync, default_adapters, plan_sync


def _parse_hosts(raw: str) -> list[HostId]:
    if raw == "all":
        return list(HostId)
    return [HostId(name.strip()) for name in raw.split(",") if name.strip()]


def _resolve_hosts(root: Path, raw: str | None) -> list[HostId]:
    if raw is not None:
        return _parse_hosts(raw)
    return list(load_config(root / ".harness" / "config.toml").hosts.enabled)


def _cli_versions(
    adapters: Mapping[HostId, HostAdapter], hosts: Sequence[HostId]
) -> dict[str, str | None]:
    versions: dict[str, str | None] = {}
    for host in hosts:
        try:
            versions[host.value] = adapters[host].probe().version
        except Exception:
            # CLI 未導入でも sync は成立させる（lock に version=null で残す）
            versions[host.value] = None
    return versions


def _item_dict(item: SyncItem) -> dict[str, object]:
    return {
        "path": item.path,
        "status": str(item.status),
        "risk": item.risk.value,
        "owners": list(item.owners),
        "diff": item.diff,
    }


def _plan_dict(plan: SyncPlan) -> dict[str, object]:
    return {
        "items": [_item_dict(i) for i in plan.items],
        "conflicts": [_item_dict(i) for i in plan.conflicts],
        "collisions": list(plan.collisions),
        "diagnostics": [{**asdict(d), "level": d.level.value} for d in plan.diagnostics],
    }


def _format_text(plan: SyncPlan) -> str:
    lines = [f"変更 {len(plan.items)} 件 / 衝突 {len(plan.conflicts)} 件"]
    lines += [f"  {i.status} {i.risk.value} {i.path} ({', '.join(i.owners)})" for i in plan.items]
    for conflict in plan.conflicts:
        lines.append(f"[CONFLICT] {conflict.status} {conflict.path} ({', '.join(conflict.owners)})")
        if conflict.diff:
            lines.append(conflict.diff.rstrip("\n"))
    lines += [f"[COLLISION] {c}" for c in plan.collisions]
    lines += [f"[{d.level}] {d.code}: {d.message}" for d in plan.diagnostics]
    return "\n".join(lines)


def _has_error(plan: SyncPlan) -> bool:
    return any(d.level is DiagnosticLevel.ERROR for d in plan.diagnostics)


def _confirm() -> bool:
    if not sys.stdin.isatty():
        print("承認が必要です。対話モードで再実行してください", file=sys.stderr)
        return False
    return input("適用しますか? [y/N] ").strip().lower() == "y"


def _apply(
    root: Path,
    hosts: list[HostId],
    plan: SyncPlan,
    overwrite: list[str],
    adapters: Mapping[HostId, HostAdapter],
) -> int:
    unresolved = [c for c in plan.conflicts if c.path not in overwrite]
    if _has_error(plan) or unresolved:
        print("衝突または ERROR があるため適用しません", file=sys.stderr)
        return 1
    needs_approval = bool(overwrite) or any(
        i.risk is RiskRank.R2 and i.status != "UNCHANGED" for i in plan.items
    )
    if needs_approval and not _confirm():
        return 1
    try:
        written = apply_sync(
            root,
            plan,
            overwrite=overwrite,
            seh_version=__version__,
            cli_versions=_cli_versions(adapters, hosts),
        )
    except SyncError as error:
        print(str(error), file=sys.stderr)
        return 1
    print(f"{len(written)} 件を書き込みました")
    return 0


def _handle(args: argparse.Namespace) -> int:
    root = Path(args.root)
    try:
        hosts = _resolve_hosts(root, args.hosts)
        spec = load_spec(root / ".harness" / "spec")
    except FileNotFoundError:
        print("config.toml がありません。seh init を先に実行してください", file=sys.stderr)
        return 1
    except (ConfigError, SpecError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 1
    adapters = default_adapters()
    plan = plan_sync(root, hosts, spec=spec, adapters=adapters)
    if args.format == "json":
        print(json.dumps(_plan_dict(plan), ensure_ascii=False, indent=2))
    else:
        print(_format_text(plan))
    if args.apply:
        return _apply(root, hosts, plan, list(args.overwrite), adapters)
    return 1 if _has_error(plan) or plan.conflicts else 0


def register(subparsers: "argparse._SubParsersAction[argparse.ArgumentParser]") -> None:
    parser = subparsers.add_parser("sync", help="正本 spec から各ホストの生成物を同期する")
    parser.add_argument("--root", default=".", help="対象リポジトリのルート")
    parser.add_argument("--hosts", default=None, help="all または claude,codex,...（既定: config）")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--plan", action="store_true", help="計画を表示する（書込なし）")
    mode.add_argument("--apply", action="store_true", help="計画を適用する")
    parser.add_argument("--overwrite", nargs="+", action="extend", default=[], metavar="PATH")
    parser.add_argument("--format", choices=("text", "json"), default="text")
    parser.set_defaults(handler=_handle)
