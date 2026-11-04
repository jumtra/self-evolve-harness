# ハンドラ契約: handler(args: argparse.Namespace) -> int（戻り値が終了コード）。
import argparse
import asyncio
import json
import sys
import tempfile
from dataclasses import asdict
from pathlib import Path

from seh.evals.fixtures import DEFAULT_SUITE_ROOT, FixtureError, load_suite
from seh.evals.report import compare, from_json, render_markdown, summarize, to_json
from seh.evals.runner import run_eval
from seh.evals.variants import VARIANTS
from seh.runtime.agent_runner import RunnerRegistry

HOSTS = ("claude", "codex", "opencode", "antigravity")
SPLITS = frozenset({"training", "regression", "holdout"})
# 実 Runner は後続タスクがここへ登録する。CI テストは差し替えた Fake を注入する
REGISTRY = RunnerRegistry()


def _run(args: argparse.Namespace) -> int:
    if args.host == "antigravity":
        print("POLICY_BLOCKED: antigravity は eval の自動実行対象外です", file=sys.stderr)
        return 1
    try:
        runner = REGISTRY.get(args.host)
    except KeyError:
        print(f"{args.host} の Runner は未実装です", file=sys.stderr)
        return 1
    splits = None
    if args.split:
        splits = {s.strip() for s in args.split.split(",") if s.strip()}
        if not splits <= SPLITS:
            print(f"不明な split: {', '.join(sorted(splits - SPLITS))}", file=sys.stderr)
            return 1
    if args.trials < 1:
        print("--trials は 1 以上を指定してください", file=sys.stderr)
        return 1
    root = Path(args.root)
    suite = Path(args.suite) if args.suite else DEFAULT_SUITE_ROOT
    try:
        cases = load_suite(suite if suite.is_absolute() else root / suite)
    except FixtureError as e:
        print(f"suite を読めません: {e}", file=sys.stderr)
        return 1
    with tempfile.TemporaryDirectory(prefix="seh-eval-") as workroot:
        run = asyncio.run(
            run_eval(
                cases,
                VARIANTS[args.variant],
                runner,
                trials=args.trials,
                workroot=Path(workroot),
                splits=splits,
            )
        )
    out = (
        Path(args.out)
        if args.out
        else root / ".harness" / "artifacts" / "eval" / f"{run.run_id}.json"
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(to_json(run), encoding="utf-8")
    print(render_markdown([run], None))
    print(f"結果: {out}")
    for s in summarize(run):
        print(f"{s.case_id} ({s.split}): {s.passes}/{s.trials}")
    return 0


def _compare(args: argparse.Namespace) -> int:
    try:
        baseline = from_json(Path(args.baseline).read_text(encoding="utf-8"))
        candidate = from_json(Path(args.candidate).read_text(encoding="utf-8"))
    except (OSError, ValueError, KeyError, TypeError) as e:
        print(f"結果 JSON を読めません: {e}", file=sys.stderr)
        return 1
    result = compare(baseline, candidate)
    if args.format == "json":
        print(json.dumps(asdict(result), ensure_ascii=False, indent=2))
    else:
        print(render_markdown([baseline, candidate], result))
    return 0 if result.promotable else 1


def register(subparsers: "argparse._SubParsersAction[argparse.ArgumentParser]") -> None:
    parser = subparsers.add_parser("eval", help="Variant を fixture で評価・比較する")
    sub = parser.add_subparsers(dest="eval_command", required=True, metavar="<action>")

    run = sub.add_parser("run", help="Variant を eval suite で実行する")
    run.add_argument("--root", default=".", help="対象リポジトリのルート")
    run.add_argument("--suite", help="suite ディレクトリ（既定 tests/fixtures/eval）")
    run.add_argument("--variant", required=True, choices=tuple(VARIANTS))
    run.add_argument("--trials", type=int, default=1)
    run.add_argument("--host", required=True, choices=HOSTS)
    run.add_argument("--split", help="カンマ区切り: training,regression,holdout")
    run.add_argument("--out", help="結果 JSON の保存先")
    run.set_defaults(handler=_run)

    cmp_ = sub.add_parser("compare", help="2 つの結果 JSON を比較する")
    cmp_.add_argument("baseline")
    cmp_.add_argument("candidate")
    cmp_.add_argument("--format", choices=("text", "json"), default="text")
    cmp_.set_defaults(handler=_compare)
