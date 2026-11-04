import pytest

from seh.evals.report import compare, from_json, render_markdown, summarize, to_json
from seh.evals.runner import EvalRun, TrialResult


def test_summarize_reports_pass_rate_and_medians():
    run = EvalRun(
        run_id="eval-V0-1",
        created_at="2026-01-01T00:00:00+00:00",
        variant_id="V0",
        components={},
        environment={},
        trials=(
            TrialResult("E01", "training", 0, "PASS", 1, 0, 0, 1.0, 100, 10, 0.1, None, ()),
            TrialResult("E01", "training", 1, "FAIL", 2, 1, 0, 3.0, 300, 30, 0.3, None, ()),
        ),
    )

    (summary,) = summarize(run)

    assert (summary.case_id, summary.passes, summary.trials) == ("E01", 1, 2)
    assert summary.pass_rate == 0.5
    assert summary.median_tokens == 220
    assert summary.median_latency == 2.0
    assert summary.total_cost == pytest.approx(0.4)
    assert summary.retries == 1


def test_summarize_marks_unknown_when_any_trial_lacks_usage():
    run = EvalRun(
        "eval-V0-1",
        "2026-01-01T00:00:00+00:00",
        "V0",
        {},
        {},
        (
            TrialResult("E01", "training", 0, "PASS", 1, 0, 0, 1.0, 100, 10, 0.1, None, ()),
            TrialResult("E01", "training", 1, "PASS", 1, 0, 0, 1.0, None, None, None, None, ()),
        ),
    )

    (summary,) = summarize(run)

    assert summary.median_tokens is None
    assert summary.total_cost is None


def test_compare_blocks_promotion_when_a_regression_case_drops_despite_improvement():
    baseline = EvalRun(
        "b",
        "t",
        "V0",
        {},
        {},
        (
            TrialResult("E01", "training", 0, "FAIL", 1, 0, 0, 1.0, None, None, None, None, ()),
            TrialResult("E02", "regression", 0, "PASS", 1, 0, 0, 1.0, None, None, None, None, ()),
        ),
    )
    candidate = EvalRun(
        "c",
        "t",
        "V1",
        {},
        {},
        (
            TrialResult("E01", "training", 0, "PASS", 1, 0, 0, 1.0, None, None, None, None, ()),
            TrialResult("E02", "regression", 0, "FAIL", 1, 0, 0, 1.0, None, None, None, None, ()),
        ),
    )

    result = compare(baseline, candidate)

    assert result.improved == ("E01",)
    assert result.regressed == ("E02",)
    assert result.must_regressions == ("E02",)
    assert result.promotable is False


def test_compare_is_promotable_when_must_cases_hold_and_others_improve():
    baseline = EvalRun(
        "b",
        "t",
        "V0",
        {},
        {},
        (
            TrialResult("E01", "training", 0, "FAIL", 1, 0, 0, 1.0, None, None, None, None, ()),
            TrialResult("E03", "holdout", 0, "PASS", 1, 0, 0, 1.0, None, None, None, None, ()),
        ),
    )
    candidate = EvalRun(
        "c",
        "t",
        "V1",
        {},
        {},
        (
            TrialResult("E01", "training", 0, "PASS", 1, 0, 0, 1.0, None, None, None, None, ()),
            TrialResult("E03", "holdout", 0, "PASS", 1, 0, 0, 1.0, None, None, None, None, ()),
        ),
    )

    result = compare(baseline, candidate)

    assert result.improved == ("E01",)
    assert result.must_regressions == ()
    assert result.promotable is True


def test_compare_not_promotable_when_must_case_is_not_fully_passing():
    baseline = EvalRun(
        "b",
        "t",
        "V0",
        {},
        {},
        (TrialResult("E03", "holdout", 0, "FAIL", 1, 0, 0, 1.0, None, None, None, None, ()),),
    )
    candidate = EvalRun(
        "c",
        "t",
        "V1",
        {},
        {},
        (TrialResult("E03", "holdout", 0, "FAIL", 1, 0, 0, 1.0, None, None, None, None, ()),),
    )

    result = compare(baseline, candidate)

    assert result.must_regressions == ()
    assert result.promotable is False


def test_render_markdown_shows_unknown_for_missing_usage_and_never_zero():
    run = EvalRun(
        "eval-V0-1",
        "2026-01-01T00:00:00+00:00",
        "V0",
        {"prompt": "a" * 64},
        {"python": "3.11"},
        (TrialResult("E01", "training", 0, "PASS", 1, 0, 0, 1.5, None, None, None, None, ()),),
    )

    text = render_markdown([run], None)

    assert "UNKNOWN" in text
    assert "$0" not in text
    assert "0 tokens" not in text
    assert "1/1" in text


def test_render_markdown_shows_unmeasured_for_run_without_trials():
    run = EvalRun("eval-V1-1", "t", "V1", {}, {}, ())

    text = render_markdown([run], None)

    assert "未計測" in text


def test_json_roundtrip_preserves_run_including_none_usage():
    run = EvalRun(
        "eval-V0-1",
        "2026-01-01T00:00:00+00:00",
        "V0",
        {"prompt": "abc"},
        {"python": "3.11", "runner_version": None},
        (
            TrialResult(
                "E01",
                "training",
                0,
                "FAIL",
                1,
                0,
                0,
                1.5,
                None,
                None,
                None,
                "X",
                ("artifact://a/b",),
            ),
        ),
    )

    restored = from_json(to_json(run))

    assert restored == run
