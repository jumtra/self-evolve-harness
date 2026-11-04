import argparse

from seh import __version__
from seh.commands import register_all


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="seh", description="self-evolve-harness CLI")
    parser.add_argument("--version", action="version", version=f"seh {__version__}")
    register_all(parser.add_subparsers(dest="command", metavar="<command>"))
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    handler = getattr(args, "handler", None)
    if handler is None:
        parser.print_help()
        return 2
    return handler(args)
