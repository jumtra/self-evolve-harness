# ハンドラ契約: handler(args: argparse.Namespace) -> int（戻り値が終了コード）。
import argparse
import sys


def _handle(args: argparse.Namespace) -> int:
    print("未実装: seh work", file=sys.stderr)
    return 2


def register(subparsers: "argparse._SubParsersAction[argparse.ArgumentParser]") -> None:
    parser = subparsers.add_parser("work", help="work（未実装）")
    parser.set_defaults(handler=_handle)
