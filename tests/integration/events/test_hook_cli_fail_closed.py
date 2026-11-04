import io
import json
import sys
from pathlib import Path

import pytest

from seh.cli import main


def _exploding_policy() -> None:
    raise RuntimeError("boom")


def test_failure_outside_run_hook_blocks_pretooluse(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    monkeypatch.setattr(
        sys,
        "stdin",
        io.TextIOWrapper(
            io.BytesIO(
                json.dumps(
                    {"tool_name": "Bash", "tool_input": {"command": "ls"}, "cwd": "/"}
                ).encode()
            )
        ),
    )
    monkeypatch.setattr("seh.commands.hook.Policy", _exploding_policy)

    code = main(["hook", "PreToolUse", "--root", str(tmp_path)])

    assert code == 2
    assert capsys.readouterr().err != ""


def test_failure_outside_run_hook_returns_deny_json_for_antigravity(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(json.dumps({}).encode())))
    monkeypatch.setattr("seh.commands.hook.Policy", _exploding_policy)

    code = main(["hook", "PreToolUse", "--host", "antigravity", "--root", str(tmp_path)])

    assert code == 0
    assert json.loads(capsys.readouterr().out)["decision"] == "deny"


def test_failure_outside_run_hook_blocks_unknown_event(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(json.dumps({}).encode())))
    monkeypatch.setattr("seh.commands.hook.Policy", _exploding_policy)

    code = main(["hook", "Bogus", "--root", str(tmp_path)])

    assert code == 2


def test_failure_outside_run_hook_does_not_block_non_blocking_event(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(json.dumps({}).encode())))
    monkeypatch.setattr("seh.commands.hook.Policy", _exploding_policy)

    code = main(["hook", "SessionStart", "--root", str(tmp_path)])

    assert code == 0


def test_unattended_flag_turns_ask_into_block(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    payload = {"tool_name": "Bash", "tool_input": {"command": "git push"}, "cwd": str(tmp_path)}
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(json.dumps(payload).encode())))

    code = main(["hook", "PreToolUse", "--unattended", "--root", str(tmp_path)])

    assert code == 2


def test_unattended_env_turns_ask_into_block(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    payload = {"tool_name": "Bash", "tool_input": {"command": "git push"}, "cwd": str(tmp_path)}
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(json.dumps(payload).encode())))
    monkeypatch.setenv("SEH_UNATTENDED", "1")

    code = main(["hook", "PreToolUse", "--root", str(tmp_path)])

    assert code == 2
