import io
import json
import sys
from pathlib import Path

import pytest

from seh.cli import main


def test_hook_cli_blocks_sensitive_write_with_exit_2(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    payload = json.dumps(
        {"tool_name": "Write", "tool_input": {"file_path": ".env"}, "cwd": str(tmp_path)}
    ).encode()
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(payload)))

    code = main(["hook", "PreToolUse", "--host", "claude", "--root", str(tmp_path)])

    assert code == 2
    assert capsys.readouterr().err != ""


def test_hook_cli_allows_ordinary_command_silently(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    payload = json.dumps(
        {"tool_name": "Bash", "tool_input": {"command": "ls"}, "cwd": str(tmp_path)}
    ).encode()
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(payload)))

    code = main(["hook", "PreToolUse", "--root", str(tmp_path)])

    captured = capsys.readouterr()
    assert code == 0
    assert captured.out == ""
    assert captured.err == ""


def test_hook_cli_ask_prints_claude_json(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    payload = json.dumps(
        {
            "tool_name": "Bash",
            "tool_input": {"command": "git push origin main"},
            "cwd": str(tmp_path),
        }
    ).encode()
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(payload)))

    code = main(["hook", "PreToolUse", "--host", "claude", "--root", str(tmp_path)])

    out = json.loads(capsys.readouterr().out)
    assert code == 0
    assert out["hookSpecificOutput"]["permissionDecision"] == "ask"


def test_hook_cli_writes_trace_when_harness_dir_exists(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    (tmp_path / ".harness").mkdir()
    payload = json.dumps(
        {"tool_name": "Bash", "tool_input": {"command": "ls"}, "cwd": str(tmp_path)}
    ).encode()
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(payload)))

    main(["hook", "PreToolUse", "--root", str(tmp_path)])

    assert (tmp_path / ".harness" / "state" / "hook-trace.jsonl").is_file()


def test_hook_cli_skips_trace_without_harness_dir(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    payload = json.dumps(
        {"tool_name": "Bash", "tool_input": {"command": "ls"}, "cwd": str(tmp_path)}
    ).encode()
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(payload)))

    main(["hook", "PreToolUse", "--root", str(tmp_path)])

    assert not (tmp_path / ".harness").exists()


def test_hook_cli_blocks_malformed_stdin(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(b"{broken")))

    code = main(["hook", "PreToolUse", "--root", str(tmp_path)])

    assert code == 2
