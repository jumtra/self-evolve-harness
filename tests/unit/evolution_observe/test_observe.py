import json
import os
from datetime import UTC, datetime
from pathlib import Path

from seh.contracts.module import MemoryRecord
from seh.evolution.observe import ObservationKind, observe, observe_with_errors
from seh.providers.memory.files import FileMemoryProvider

NOW = datetime(2026, 11, 4, tzinfo=UTC)


def test_three_pending_feedbacks_with_same_title_are_actionable(tmp_path):
    memory = FileMemoryProvider(tmp_path)
    memdir = tmp_path / ".agent-memory"
    memdir.mkdir()
    for name in ("a", "b", "c"):
        (memdir / f"feedback_{name}.md").write_text(
            "---\nname: x\ndescription: 日本語で返す\nmetadata:\n  type: feedback\n"
            "  evolve: pending\n---\n本文\n",
            encoding="utf-8",
        )

    result = observe(tmp_path, memory=memory, now=NOW)

    assert len(result) == 1
    assert result[0].kind is ObservationKind.FEEDBACK
    assert result[0].count == 3
    assert result[0].actionable is True
    assert result[0].evidence_refs == (
        "memory:feedback_a",
        "memory:feedback_b",
        "memory:feedback_c",
    )


def test_done_feedback_is_excluded_and_count_metadata_is_summed(tmp_path):
    memory = FileMemoryProvider(tmp_path)
    memdir = tmp_path / ".agent-memory"
    memdir.mkdir()
    (memdir / "feedback_a.md").write_text(
        "---\nname: x\ndescription: Keep tests\nmetadata:\n  type: feedback\n"
        "  evolve: pending\n  count: 2\n---\nb\n",
        encoding="utf-8",
    )
    (memdir / "feedback_b.md").write_text(
        "---\nname: x\ndescription: Keep tests\nmetadata:\n  type: feedback\n---\nb\n",
        encoding="utf-8",
    )
    (memdir / "feedback_c.md").write_text(
        "---\nname: y\ndescription: Old thing\nmetadata:\n  type: feedback\n"
        "  evolve: done\n  count: 9\n---\nb\n",
        encoding="utf-8",
    )

    result = observe(tmp_path, memory=memory, now=NOW)

    assert [(o.key, o.count) for o in result] == [("feedback:keep_tests", 3)]


def test_non_feedback_memory_is_ignored(tmp_path):
    memory = FileMemoryProvider(tmp_path)
    memory.save(MemoryRecord("", "project", "Some note", "body"))

    result = observe(tmp_path, memory=memory, now=NOW)

    assert result == []


def test_retries_of_same_node_in_one_run_count_once(tmp_path):
    attempts = tmp_path / ".harness/state/runs/run1/attempts"
    attempts.mkdir(parents=True)
    lines = [
        json.dumps(
            {
                "attempt": n,
                "run_id": "run1",
                "terminal_state": "FAILED",
                "verdict_status": "FAIL",
                "reason_code": "TEST_FAILED",
                "evidence_refs": [],
            }
        )
        for n in (1, 2, 3)
    ]
    (attempts / "node-a.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.utime(attempts / "node-a.jsonl", (NOW.timestamp(), NOW.timestamp()))

    result = observe(tmp_path, memory=None, now=NOW)

    assert len(result) == 1
    assert result[0].key == "failure:TEST_FAILED"
    assert result[0].count == 1
    assert result[0].actionable is False


def test_same_reason_in_two_runs_is_actionable(tmp_path):
    for run in ("run1", "run2"):
        attempts = tmp_path / f".harness/state/runs/{run}/attempts"
        attempts.mkdir(parents=True)
        record = {
            "attempt": 1,
            "run_id": run,
            "terminal_state": "FAILED",
            "verdict_status": "FAIL",
            "reason_code": "TEST_FAILED",
            "evidence_refs": [],
        }
        path = attempts / "node-a.jsonl"
        path.write_text(json.dumps(record) + "\n", encoding="utf-8")
        os.utime(path, (NOW.timestamp(), NOW.timestamp()))

    result = observe(tmp_path, memory=None, now=NOW)

    assert result[0].count == 2
    assert result[0].actionable is True
    assert result[0].evidence_refs == (
        "attempt:run1:node-a:1",
        "attempt:run2:node-a:1",
    )


def test_hook_denials_are_aggregated_by_reason_code(tmp_path):
    state = tmp_path / ".harness/state"
    state.mkdir(parents=True)
    events = []
    for i, (run, decision, reason) in enumerate(
        [
            ("r1", "deny", "SECRET_FILE"),
            ("r2", "ask", "SECRET_FILE"),
            ("r2", "allow", "SECRET_FILE"),
            ("r3", "deny", "OTHER"),
        ]
    ):
        events.append(
            json.dumps(
                {
                    "ts": "2026-11-03T00:00:00+00:00",
                    "event_id": f"e{i}",
                    "event": "hook.decision",
                    "run_id": run,
                    "task_id": None,
                    "node_id": None,
                    "data": {"decision": decision, "reason_code": reason},
                    "evidence_digest": None,
                }
            )
        )
    (state / "hook-trace.jsonl").write_text("\n".join(events) + "\n", encoding="utf-8")

    result = observe(tmp_path, memory=None, now=NOW)

    assert [(o.key, o.count, o.actionable) for o in result] == [
        ("hook:SECRET_FILE", 2, True),
        ("hook:OTHER", 1, False),
    ]
    assert result[0].evidence_refs == ("trace:r1:e0", "trace:r2:e1")
    assert result[0].first_seen == "2026-11-03T00:00:00+00:00"


def test_eval_pass_then_fail_is_a_regression(tmp_path):
    evals = tmp_path / ".harness/artifacts/eval"
    evals.mkdir(parents=True)
    for run_id, created, status in [
        ("old", "2026-10-01T00:00:00+00:00", "PASS"),
        ("new", "2026-11-01T00:00:00+00:00", "FAIL"),
    ]:
        (evals / f"{run_id}.json").write_text(
            json.dumps(
                {
                    "run_id": run_id,
                    "created_at": created,
                    "trials": [
                        {"case_id": "case1", "verdict_status": status},
                        {"case_id": "case2", "verdict_status": "PASS"},
                    ],
                }
            ),
            encoding="utf-8",
        )

    result = observe(tmp_path, memory=None, now=NOW)

    assert len(result) == 1
    assert result[0].kind is ObservationKind.EVAL_REGRESSION
    assert result[0].key == "eval:case1"
    assert result[0].count == 1
    assert result[0].actionable is True
    assert result[0].last_seen == "2026-11-01T00:00:00+00:00"


def test_authoring_evals_directory_is_also_read(tmp_path):
    evals = tmp_path / ".harness/authoring/evals"
    evals.mkdir(parents=True)
    for run_id, created, status in [
        ("a", "2026-10-01T00:00:00+00:00", "PASS"),
        ("b", "2026-11-01T00:00:00+00:00", "FAIL"),
    ]:
        (evals / f"{run_id}.json").write_text(
            json.dumps(
                {
                    "run_id": run_id,
                    "created_at": created,
                    "trials": [{"case_id": "c", "verdict_status": status}],
                }
            ),
            encoding="utf-8",
        )

    result = observe(tmp_path, memory=None, now=NOW)

    assert [o.key for o in result] == ["eval:c"]


def test_events_older_than_window_are_ignored(tmp_path):
    state = tmp_path / ".harness/state"
    state.mkdir(parents=True)
    old = {
        "ts": "2026-01-01T00:00:00+00:00",
        "event_id": "e0",
        "event": "hook.decision",
        "run_id": "r1",
        "data": {"decision": "deny", "reason_code": "OLD"},
    }
    (state / "hook-trace.jsonl").write_text(json.dumps(old) + "\n", encoding="utf-8")

    result = observe(tmp_path, memory=None, now=NOW, window_days=90)

    assert result == []


def test_broken_lines_are_skipped_and_counted_in_last_errors(tmp_path):
    state = tmp_path / ".harness/state"
    state.mkdir(parents=True)
    good = {
        "ts": "2026-11-03T00:00:00+00:00",
        "event_id": "e0",
        "event": "hook.decision",
        "run_id": "r1",
        "data": {"decision": "deny", "reason_code": "X"},
    }
    (state / "hook-trace.jsonl").write_text("{broken\n" + json.dumps(good) + "\n", encoding="utf-8")
    evals = tmp_path / ".harness/artifacts/eval"
    evals.mkdir(parents=True)
    (evals / "bad.json").write_text("not json", encoding="utf-8")

    report = observe_with_errors(tmp_path, memory=None, now=NOW)

    assert [o.key for o in report.observations] == ["hook:X"]
    assert report.last_errors == 2


def test_secret_is_masked_in_key_and_summary(tmp_path):
    secret = "sk-" + "a" * 30
    attempts = tmp_path / ".harness/state/runs/run1/attempts"
    attempts.mkdir(parents=True)
    record = {
        "attempt": 1,
        "run_id": "run1",
        "terminal_state": "FAILED",
        "verdict_status": "FAIL",
        "reason_code": f"LEAK {secret}",
        "evidence_refs": [],
    }
    (attempts / "n.jsonl").write_text(json.dumps(record) + "\n", encoding="utf-8")
    os.utime(attempts / "n.jsonl", (NOW.timestamp(), NOW.timestamp()))

    result = observe(tmp_path, memory=None, now=NOW)

    assert secret not in result[0].summary
    assert secret not in result[0].key
    assert len(result[0].summary) <= 200


def test_observe_does_not_modify_files(tmp_path):
    state = tmp_path / ".harness/state"
    state.mkdir(parents=True)
    (state / "hook-trace.jsonl").write_text(
        json.dumps(
            {
                "ts": "2026-11-03T00:00:00+00:00",
                "event_id": "e0",
                "run_id": "r1",
                "data": {"decision": "deny", "reason_code": "X"},
            }
        )
        + "\n{broken\n",
        encoding="utf-8",
    )
    memdir = tmp_path / ".agent-memory"
    memdir.mkdir()
    (memdir / "feedback_a.md").write_text(
        "---\nname: x\ndescription: T\nmetadata:\n  type: feedback\n---\nb\n", encoding="utf-8"
    )
    before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in tmp_path.rglob("*") if p.is_file()}

    observe(tmp_path, memory=FileMemoryProvider(tmp_path), now=NOW)

    after = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in tmp_path.rglob("*") if p.is_file()}
    assert after == before


def test_order_is_kind_then_count_desc_then_key(tmp_path):
    memdir = tmp_path / ".agent-memory"
    memdir.mkdir()
    for i, title in enumerate(["Bbb", "Aaa", "Aaa", "Ccc", "Ccc", "Ccc"]):
        (memdir / f"feedback_{i}.md").write_text(
            f"---\nname: x\ndescription: {title}\nmetadata:\n  type: feedback\n---\nb\n",
            encoding="utf-8",
        )
    state = tmp_path / ".harness/state"
    state.mkdir(parents=True)
    (state / "hook-trace.jsonl").write_text(
        json.dumps(
            {
                "ts": "2026-11-03T00:00:00+00:00",
                "event_id": "e",
                "run_id": "r",
                "data": {"decision": "deny", "reason_code": "H"},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    memory = FileMemoryProvider(tmp_path)

    first = observe(tmp_path, memory=memory, now=NOW)
    second = observe(tmp_path, memory=memory, now=NOW)

    assert [o.key for o in first] == [
        "feedback:ccc",
        "feedback:aaa",
        "feedback:bbb",
        "hook:H",
    ]
    assert first == second


def test_missing_harness_dir_yields_empty(tmp_path: Path):
    assert observe(tmp_path, memory=None, now=NOW) == []
