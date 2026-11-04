from pathlib import Path

import pytest

from seh.contracts import RunContext, RunResult, TerminalState, VerdictStatus
from seh.evals.fixtures import CheckSpec, EvalCase, TaskSpec
from seh.evals.variants import VARIANTS
from seh.evolution.benchmark import benchmark
from seh.runtime.runners.fake import FakeCliRunner


async def test_benchmark_runs_both_inputs_on_all_splits(tmp_path: Path) -> None:
    fixture = tmp_path / "fixture"
    fixture.mkdir()
    cases = [
        EvalCase(
            1,
            split,
            split,
            split,
            "bugfix",
            TaskSpec("g", ()),
            fixture,
            False,
            (CheckSpec("check", "file_contains", {"path": "instruction.txt", "regex": "good"}),),
            (),
            VerdictStatus.FAIL,
            {},
        )
        for split in ("training", "regression", "holdout")
    ]
    seen: list[str] = []

    def run(prompt: str, context: RunContext) -> RunResult:
        seen.append((context.cwd / "instruction.txt").read_text())
        return RunResult("r", "claude", TerminalState.SUCCESS, 0, "done", None, (), None, None)

    runner = FakeCliRunner("claude", run)
    result = await benchmark(
        cases,
        VARIANTS["V0"],
        runner,
        trials=1,
        workroot=tmp_path / "work",
        baseline_files={"instruction.txt": b"bad"},
        candidate_files={"instruction.txt": b"good"},
    )
    assert seen == ["bad", "good"] * 3
    assert set(result.comparison.improved) == {"training", "regression", "holdout"}
    assert result.comparison.promotable


async def test_missing_required_splits_fails_closed(tmp_path: Path) -> None:
    runner = FakeCliRunner("claude", [])
    with pytest.raises(ValueError, match="split"):
        await benchmark(
            [],
            VARIANTS["V0"],
            runner,
            trials=1,
            workroot=tmp_path,
            baseline_files={},
            candidate_files={},
        )
