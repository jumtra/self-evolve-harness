# ハンドラ契約: handler(args: argparse.Namespace) -> int（戻り値が終了コード）。
import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

from seh.config import (
    Config,
    ConfigError,
    config_diff,
    defaults,
    dump_config,
    load_config,
    set_value,
)


def _config_path(root: str) -> Path:
    return Path(root) / ".harness" / "config.toml"


def _load_or_defaults(path: Path) -> tuple[Config, bool]:
    if path.exists():
        return load_config(path), True
    return defaults(), False


def _to_jsonable(cfg: Config) -> object:
    import tomllib

    return tomllib.loads(dump_config(cfg))


def _show(args: argparse.Namespace) -> int:
    path = _config_path(args.root)
    try:
        cfg, exists = _load_or_defaults(path)
    except ConfigError as e:
        print(f"設定エラー: {e}", file=sys.stderr)
        return 1
    if not exists:
        print(f"未設定: {path} がないため既定値（balanced）を表示します", file=sys.stderr)
        if args.format == "toml":
            print("# 未設定: 既定値（balanced）")
    if args.format == "json":
        print(json.dumps(_to_jsonable(cfg), ensure_ascii=False, indent=2))
    else:
        print(dump_config(cfg), end="")
    for warning in cfg.policy_warnings():
        print(f"警告: {warning}", file=sys.stderr)
    return 0


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".config-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _set(args: argparse.Namespace) -> int:
    path = _config_path(args.root)
    try:
        old, _ = _load_or_defaults(path)
        new = set_value(old, args.key, args.value)
    except ConfigError as e:
        print(f"設定エラー: {e}", file=sys.stderr)
        return 1
    diff = config_diff(old, new)
    if not diff:
        print("変更なし")
    for key, before, after in diff:
        print(f"{key}: {before!r} -> {after!r}")
    if args.apply:
        _atomic_write(path, dump_config(new))
        print(f"書き込みました: {path}")
    else:
        print("(--plan: 書き込みは行いません。反映するには --apply)")
    for warning in new.policy_warnings():
        print(f"警告: {warning}", file=sys.stderr)
    return 0


def _usage(args: argparse.Namespace) -> int:
    print("使い方: seh config {show,set} ...", file=sys.stderr)
    return 2


def register(subparsers: "argparse._SubParsersAction[argparse.ArgumentParser]") -> None:
    parser = subparsers.add_parser(
        "config", help="ハーネス設定（.harness/config.toml）の表示・変更"
    )
    parser.set_defaults(handler=_usage)
    sub = parser.add_subparsers(dest="config_action", metavar="<action>")

    show = sub.add_parser("show", help="設定を表示する")
    show.add_argument("--root", default=".", help="プロジェクトルート（既定: .）")
    show.add_argument("--format", choices=("toml", "json"), default="toml")
    show.set_defaults(handler=_show)

    setp = sub.add_parser("set", help="設定値を変更する（既定は --plan）")
    setp.add_argument("key", metavar="KEY", help="ドット表記のキー（例: runtime.max_parallel）")
    setp.add_argument("value", metavar="VALUE")
    setp.add_argument("--root", default=".", help="プロジェクトルート（既定: .）")
    mode = setp.add_mutually_exclusive_group()
    mode.add_argument("--plan", action="store_true", help="差分のみ表示（既定）")
    mode.add_argument("--apply", action="store_true", help="原子的に書き込む")
    setp.set_defaults(handler=_set)
