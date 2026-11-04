import json
from pathlib import Path

import pytest

from seh.cli import main


def test_show_without_file_prints_unset_and_defaults(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(["config", "show", "--root", str(tmp_path)])

    out = capsys.readouterr().out
    assert code == 0
    assert "未設定" in out
    assert 'profile = "balanced"' in out


def test_show_reads_existing_file(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / ".harness").mkdir()
    (tmp_path / ".harness" / "config.toml").write_text('profile = "minimal"\n')

    code = main(["config", "show", "--root", str(tmp_path)])

    assert code == 0
    assert 'profile = "minimal"' in capsys.readouterr().out


def test_show_json_format(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / ".harness").mkdir()
    (tmp_path / ".harness" / "config.toml").write_text('profile = "full"\n')

    code = main(["config", "show", "--root", str(tmp_path), "--format", "json"])

    data = json.loads(capsys.readouterr().out)
    assert code == 0
    assert data["profile"] == "full"
    assert data["runtime"]["max_parallel"] == 3


def test_show_invalid_config_exits_1_with_message_on_stderr(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / ".harness").mkdir()
    (tmp_path / ".harness" / "config.toml").write_text("[runtime]\nbogus = 1\n")

    code = main(["config", "show", "--root", str(tmp_path)])

    assert code == 1
    assert "runtime.bogus" in capsys.readouterr().err


def test_set_plan_prints_diff_and_does_not_write(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(["config", "set", "runtime.max_parallel", "5", "--root", str(tmp_path), "--plan"])

    out = capsys.readouterr().out
    assert code == 0
    assert "runtime.max_parallel" in out
    assert not (tmp_path / ".harness" / "config.toml").exists()


def test_set_without_mode_flag_behaves_as_plan(tmp_path: Path) -> None:
    code = main(["config", "set", "runtime.max_parallel", "5", "--root", str(tmp_path)])

    assert code == 0
    assert not (tmp_path / ".harness" / "config.toml").exists()


def test_set_apply_writes_file_atomically(tmp_path: Path) -> None:
    code = main(["config", "set", "runtime.max_parallel", "5", "--root", str(tmp_path), "--apply"])

    harness = tmp_path / ".harness"
    assert code == 0
    assert "max_parallel = 5" in (harness / "config.toml").read_text()
    assert [p.name for p in harness.iterdir()] == ["config.toml"]


def test_set_apply_preserves_other_values(tmp_path: Path) -> None:
    (tmp_path / ".harness").mkdir()
    (tmp_path / ".harness" / "config.toml").write_text('profile = "full"\n')

    code = main(["config", "set", "runtime.max_parallel", "5", "--root", str(tmp_path), "--apply"])

    text = (tmp_path / ".harness" / "config.toml").read_text()
    assert code == 0
    assert 'profile = "full"' in text
    assert 'mode = "managed"' in text


def test_set_invalid_value_exits_1_and_does_not_write(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(["config", "set", "runtime.max_parallel", "99", "--root", str(tmp_path), "--apply"])

    assert code == 1
    assert "runtime.max_parallel" in capsys.readouterr().err
    assert not (tmp_path / ".harness" / "config.toml").exists()


def test_set_plan_and_apply_together_is_usage_error(tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as exc:
        main(
            [
                "config",
                "set",
                "runtime.max_parallel",
                "5",
                "--root",
                str(tmp_path),
                "--plan",
                "--apply",
            ]
        )

    assert exc.value.code == 2


def test_config_without_action_is_usage_error() -> None:
    assert main(["config"]) == 2
