import json
from pathlib import Path

import pytest

from seh.cli import main


def test_list_text_shows_builtin_modules(capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["module", "list"])

    out = capsys.readouterr().out
    assert code == 0
    assert "code-intelligence.codegraph" in out
    assert "memory.file" in out


def test_list_json_has_fields(capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["module", "list", "--format", "json"])

    data = json.loads(capsys.readouterr().out)
    memory_file = next(m for m in data if m["id"] == "memory.file")
    assert code == 0
    assert memory_file["default_enabled"] is True
    assert memory_file["opt_in"] is False
    assert memory_file["provides"] == ["memory.store"]
    assert "version" in memory_file


def test_list_includes_extra_dir(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / "custom").mkdir()
    (tmp_path / "custom" / "module.toml").write_text(
        'id = "ext.custom"\napi_version = "1"\nversion = "0.1"\n'
        'provides = ["ext.cap"]\nhealth_command = []\n'
    )

    code = main(["module", "list", "--extra-dir", str(tmp_path)])

    assert code == 0
    assert "ext.custom" in capsys.readouterr().out


def test_enable_plan_success_shows_ledger(capsys: pytest.CaptureFixture[str]) -> None:
    code = main(
        ["module", "enable", "code-intelligence.codegraph", "--with", "memory.file", "--plan"]
    )

    out = capsys.readouterr().out
    assert code == 0
    assert "code.affected_tests" in out
    assert "memory.store" in out


def test_enable_plan_conflict_returns_1(capsys: pytest.CaptureFixture[str]) -> None:
    code = main(
        [
            "module",
            "enable",
            "code-intelligence.codegraph",
            "--with",
            "code-intelligence.graphify",
            "--plan",
        ]
    )

    assert code == 1
    assert "CONFLICT:" in capsys.readouterr().out


def test_enable_apply_returns_2_with_guidance(capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["module", "enable", "memory.file", "--apply"])

    assert code == 2
    assert "seh config set" in capsys.readouterr().err


def test_enable_without_plan_returns_2() -> None:
    code = main(["module", "enable", "memory.file"])

    assert code == 2


def test_bare_module_returns_2() -> None:
    code = main(["module"])

    assert code == 2
