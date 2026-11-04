from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from seh.contracts import ApprovalToken
from seh.evals.report import Comparison
from seh.evals.runner import EvalRun, TrialResult
from seh.evolution.benchmark import BenchmarkResult, overlay_digest
from seh.evolution.promote import PromotionError, promote
from seh.evolution.rollback import rollback_promotion


def trial(split, status="PASS", evidence_refs=("artifact://eval/check.log",)):
    return TrialResult(split, split, 1, status, 1, 0, 0, 0, None, None, None, None, evidence_refs)


def benchmark(files, baseline=None):
    run = EvalRun(
        "id", "now", "v", {}, {}, tuple(trial(s) for s in ("training", "regression", "holdout"))
    )
    baseline_run = EvalRun(
        "base",
        "now",
        "v",
        {},
        {},
        (trial("training", "FAIL"), trial("regression"), trial("holdout")),
    )
    return BenchmarkResult(
        baseline_run,
        run,
        Comparison(("training",), (), (), True),
        overlay_digest(files if baseline is None else baseline),
        overlay_digest(files),
    )


def test_requires_human_token_and_preserves_file(tmp_path: Path):
    (tmp_path / "a.txt").write_text("old")
    files = {"a.txt": b"new"}
    with pytest.raises(PromotionError):
        promote(tmp_path, "c1", files, benchmark(files), approval=None, now=datetime.now(UTC))
    assert (tmp_path / "a.txt").read_text() == "old"


def test_fabricated_benchmark_without_independent_evidence_is_rejected(tmp_path: Path):
    from dataclasses import replace

    (tmp_path / "a.txt").write_text("old")
    files = {"a.txt": b"new"}
    now = datetime.now(UTC)
    token = ApprovalToken(
        "t", ("evolve:promote:c1",), overlay_digest(files), now + timedelta(hours=1), "human"
    )
    ev = benchmark(files, {"a.txt": b"old"})
    unverified = replace(
        ev,
        candidate=replace(
            ev.candidate,
            trials=tuple(replace(t, evidence_refs=()) for t in ev.candidate.trials),
        ),
    )
    with pytest.raises(PromotionError, match="BENCHMARK_EVIDENCE_UNVERIFIED"):
        promote(tmp_path, "c1", files, unverified, approval=token, now=now)
    assert (tmp_path / "a.txt").read_text() == "old"


def test_promote_and_rollback(tmp_path: Path):
    (tmp_path / "a.txt").write_text("old")
    files = {"a.txt": b"new"}
    now = datetime.now(UTC)
    token = ApprovalToken(
        "t", ("evolve:promote:c1",), overlay_digest(files), now + timedelta(hours=1), "human"
    )
    snapshot = promote(
        tmp_path, "c1", files, benchmark(files, {"a.txt": b"old"}), approval=token, now=now
    )
    assert (tmp_path / "a.txt").read_text() == "new"
    rollback_promotion(tmp_path, snapshot)
    assert (tmp_path / "a.txt").read_text() == "old"


def test_stale_evidence_refuses_modified_candidate(tmp_path):
    now = datetime.now(UTC)
    files = {"a.txt": b"new"}
    token = ApprovalToken(
        "t", ("evolve:promote:c1",), overlay_digest(files), now + timedelta(hours=1), "human"
    )
    with pytest.raises(PromotionError):
        promote(tmp_path, "c1", files, benchmark({"a.txt": b"old"}), approval=token, now=now)


def test_lifecycle_retire_only_generated_expired():
    from seh.evolution.lifecycle import CandidateRecord, retire_stale

    now = datetime.now(UTC)
    records = [
        CandidateRecord("one", "proposed", now - timedelta(days=4), True),
        CandidateRecord("user", "proposed", now - timedelta(days=4), False),
    ]
    result = retire_stale(records, now=now, max_age=timedelta(days=1))
    assert result[0].status == "retired"
    assert result[1].status == "proposed"


def test_learning_records_verified_constraint(tmp_path):
    from seh.evolution.learning import record_learning
    from seh.knowledge import constraints_for

    now = datetime.now(UTC)
    record = tmp_path / ".harness/evolution/promotions/candidate1.json"
    record.parent.mkdir(parents=True)
    record.write_text('{"snapshot_id":"candidate1","evidence_refs":["eval:1"]}')
    record_learning(
        tmp_path,
        id="learn1",
        statement="Keep tests passing",
        scope_globs=("src/**",),
        source_record="candidate1",
        evidence_refs=("eval:1",),
        now=now,
    )
    assert constraints_for(tmp_path, ["src/a.py"], now=now)[0].id == "learn1"


def test_rollback_refuses_user_changes_after_promotion(tmp_path):
    (tmp_path / "a.txt").write_text("old")
    files = {"a.txt": b"new"}
    now = datetime.now(UTC)
    token = ApprovalToken(
        "t", ("evolve:promote:c1",), overlay_digest(files), now + timedelta(hours=1), "human"
    )
    snapshot = promote(
        tmp_path, "c1", files, benchmark(files, {"a.txt": b"old"}), approval=token, now=now
    )
    (tmp_path / "a.txt").write_text("user edit")
    with pytest.raises(ValueError):
        rollback_promotion(tmp_path, snapshot)
    assert (tmp_path / "a.txt").read_text() == "user edit"


def test_missing_regression_case_fails_closed(tmp_path):
    from dataclasses import replace

    (tmp_path / "a.txt").write_text("old")
    files = {"a.txt": b"new"}
    now = datetime.now(UTC)
    token = ApprovalToken(
        "t", ("evolve:promote:c1",), overlay_digest(files), now + timedelta(hours=1), "human"
    )
    evidence = benchmark(files, {"a.txt": b"old"})
    extra = replace(trial("regression", "FAIL"), case_id="missing")
    evidence = replace(
        evidence, baseline=replace(evidence.baseline, trials=(*evidence.baseline.trials, extra))
    )
    with pytest.raises(PromotionError):
        promote(tmp_path, "c1", files, evidence, approval=token, now=now)


def test_direct_promotion_rejects_authoring_without_authoring_gate(tmp_path: Path):
    files = {".harness/spec/skills/a.yaml": b"new"}
    now = datetime.now(UTC)
    token = ApprovalToken(
        "t", ("evolve:promote:c1",), overlay_digest(files), now + timedelta(hours=1), "human"
    )
    with pytest.raises(PromotionError, match="AUTHORING_RECORD_REQUIRED"):
        promote(
            tmp_path,
            "c1",
            files,
            benchmark(files, {".harness/spec/skills/a.yaml": None}),
            approval=token,
            now=now,
        )
    assert not (tmp_path / ".harness/spec/skills/a.yaml").exists()
