"""候補と基準を同じ評価ケースで比較する。"""

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path

from seh.artifacts import ArtifactStore
from seh.contracts import CliAgentRunner
from seh.evals.fixtures import EvalCase
from seh.evals.report import Comparison, compare
from seh.evals.runner import EvalRun, run_eval
from seh.evals.variants import Variant

_SPLITS = ("training", "regression", "holdout")


@dataclass(frozen=True)
class BenchmarkResult:
    baseline: EvalRun
    candidate: EvalRun
    comparison: Comparison
    baseline_digest: str = ""
    candidate_digest: str = ""


def overlay_digest(files: Mapping[str, bytes | None]) -> str:
    digest = hashlib.sha256()
    for path, content in sorted(files.items()):
        name = path.encode("utf-8")
        digest.update(len(name).to_bytes(8, "big"))
        digest.update(name)
        digest.update(b"\x00" if content is None else b"\x01")
        if content is not None:
            digest.update(len(content).to_bytes(8, "big"))
            digest.update(content)
    return digest.hexdigest()


async def benchmark(
    cases: Sequence[EvalCase],
    variant: Variant,
    runner: CliAgentRunner,
    *,
    trials: int,
    workroot: Path,
    baseline_files: Mapping[str, bytes | None],
    candidate_files: Mapping[str, bytes | None],
) -> BenchmarkResult:
    if set(baseline_files) != set(candidate_files):
        raise ValueError("baseline and candidate file paths must match")
    if not set(_SPLITS).issubset({case.split for case in cases}):
        raise ValueError("training, regression and holdout splits are required")
    if len({case.id for case in cases}) != len(cases):
        raise ValueError("case ids must be unique")
    store = ArtifactStore(workroot / "artifacts")
    before: list[EvalRun] = []
    after: list[EvalRun] = []
    for split in _SPLITS:
        for overlay, output in ((baseline_files, before), (candidate_files, after)):
            output.append(
                await run_eval(
                    cases,
                    variant,
                    runner,
                    trials=trials,
                    workroot=workroot,
                    artifacts=store,
                    splits={split},
                    overlay=overlay,
                )
            )
    baseline = replace(before[0], trials=tuple(t for run in before for t in run.trials))
    candidate = replace(after[0], trials=tuple(t for run in after for t in run.trials))
    return BenchmarkResult(
        baseline,
        candidate,
        compare(baseline, candidate),
        overlay_digest(baseline_files),
        overlay_digest(candidate_files),
    )
