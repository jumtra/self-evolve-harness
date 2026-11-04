import json
import time
from pathlib import Path

import pytest

from seh.cli import main
from seh.doctor import DoctorContext, run_doctor


def test_text_output_and_exit_code_zero_for_info_only(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(["doctor", "--root", str(tmp_path)])

    out = capsys.readouterr().out
    assert code == 0
    assert "[INFO] config: NOT_CONFIGURED — " in out
    assert "seh init" in out


def test_error_finding_gives_exit_code_one(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / ".harness").mkdir()
    (tmp_path / ".harness" / "config.toml").write_text('profile = "bogus"\n', encoding="utf-8")

    code = main(["doctor", "--root", str(tmp_path)])

    assert code == 1
    assert "[ERROR] config: CONFIG_INVALID — " in capsys.readouterr().out


def test_json_output_is_array_of_findings(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(["doctor", "--root", str(tmp_path), "--format", "json"])

    data = json.loads(capsys.readouterr().out)
    assert code == 0
    assert {"check": "config", "level": "INFO", "code": "NOT_CONFIGURED"}.items() <= next(
        d for d in data if d["code"] == "NOT_CONFIGURED"
    ).items()
    assert set(data[0]) == {"check", "level", "code", "message", "path"}


def test_context_flag_adds_context_size(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / "CLAUDE.md").write_text("hello\n", encoding="utf-8")

    without = main(["doctor", "--root", str(tmp_path), "--format", "json"])
    out_without = capsys.readouterr().out
    with_flag = main(["doctor", "--root", str(tmp_path), "--format", "json", "--context"])
    out_with = capsys.readouterr().out

    assert without == with_flag == 0
    assert "CONTEXT_SIZE" not in out_without
    assert "CONTEXT_SIZE" in out_with


def test_run_doctor_on_small_repo_finishes_under_one_second(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / ".harness").mkdir()
    (tmp_path / ".harness" / "config.toml").write_text('profile = "balanced"\n', encoding="utf-8")
    (tmp_path / "CLAUDE.md").write_text("hello\n", encoding="utf-8")
    ctx = DoctorContext(root=tmp_path, options={"context": True})

    started = time.perf_counter()
    run_doctor(ctx)
    elapsed = time.perf_counter() - started

    print(f"run_doctor elapsed: {elapsed:.4f}s")
    assert elapsed < 1.0
