import argparse
from importlib import import_module

# 後続タスクが各グループのファイルだけを編集すればよいよう、登録順をここで固定する。
GROUPS: tuple[str, ...] = (
    "init",
    "doctor",
    "config",
    "module",
    "sync",
    "work",
    "eval",
    "author",
    "evolve",
    "migrate",
    "hook",
)


def register_all(subparsers: "argparse._SubParsersAction[argparse.ArgumentParser]") -> None:
    for group in GROUPS:
        import_module(f"seh.commands.{group}").register(subparsers)
