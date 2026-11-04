from __future__ import annotations

from pathlib import Path

import pytest

from seh.cli import main
from seh.contracts import TerminalState
from seh.contracts.state import UnitState
from seh.runtime.checkpoint import CheckpointStore
from seh.runtime.repair import AttemptRecord
from seh.runtime.scheduler import NodeOutcome, SchedulerState


def test_native_mode_is_redirected_to_host_skill_with_exit_2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(["work", "run", "--task", "x.json", "--root", str(tmp_path), "--mode", "native"])

    captured = capsys.readouterr()
    assert code == 2
    assert "native モードは各ホストの /work Skill から実行します" in captured.out + captured.err


def test_status_of_unknown_run_fails(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["work", "status", "nope", "--root", str(tmp_path)])

    assert code == 1
    assert "nope" in capsys.readouterr().err


def test_status_shows_node_states_attempts_and_stopped_reason(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    store = CheckpointStore(tmp_path, "r1")
    store.save_state(
        SchedulerState(
            {"w1": UnitState.PASSED, "w2": UnitState.PENDING},
            {"w1": NodeOutcome("w1", UnitState.PASSED, None)},
            stopped_reason="BUDGET_EXCEEDED:time",
        ),
        budget_spent={"elapsed_seconds": 1.5},
    )
    store.append_attempt("w1", AttemptRecord(1, "x", TerminalState.SUCCESS, "FAIL", "BAD", ()))
    store.append_attempt("w1", AttemptRecord(2, "y", TerminalState.SUCCESS, "PASS", "OK", ()))

    code = main(["work", "status", "r1", "--root", str(tmp_path)])

    out = capsys.readouterr().out
    assert code == 0
    assert "BUDGET_EXCEEDED:time" in out
    assert "w1" in out and "PASSED" in out and "attempts=2" in out
    assert "w2" in out and "PENDING" in out


def test_resume_of_unknown_run_fails(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["work", "resume", "nope", "--root", str(tmp_path)])

    assert code == 1
    assert "nope" in capsys.readouterr().err
