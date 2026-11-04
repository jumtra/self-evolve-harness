from pathlib import Path

import pytest

from seh.contracts import VerdictStatus
from seh.evals.checker import run_checks
from seh.evals.fixtures import EvalCase, load_case, load_suite, materialize


@pytest.mark.parametrize("case", load_suite(), ids=lambda c: c.id)
async def test_noop_implementation_gets_expected_verdict(case: EvalCase, tmp_path: Path):
    work = materialize(case, tmp_path / "work")

    verdict, _ = await run_checks(case, work)

    assert verdict.status is case.expected_verdict_for_noop
    assert verdict.status is VerdictStatus.FAIL


async def test_e01_correct_patch_passes(tmp_path: Path):
    case = load_case(Path("tests/fixtures/eval/E01"))
    work = materialize(case, tmp_path / "work")
    stats = work / "stats.py"
    stats.write_text(stats.read_text().replace("(len(values) - 1)", "len(values)"))

    verdict, _ = await run_checks(case, work)

    assert verdict.status is VerdictStatus.PASS
