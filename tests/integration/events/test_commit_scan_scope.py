import subprocess
from pathlib import Path

import pytest

from seh.contracts import HostId
from seh.events import HookDecision, HookInput, evaluate
from seh.policy import Policy

DUMMY = "gh" + "p_" + "A1b2C3d4E5" * 4


def test_diff_failure_is_fail_closed(tmp_path: Path) -> None:
    inp = HookInput("PreToolUse", HostId.CLAUDE, "Bash", "git commit -m x", (), tmp_path, {})
    outcome = evaluate(inp, policy=Policy())

    assert outcome.decision == HookDecision.DENY
    assert outcome.reason_code == "SECRET_SCAN_FAILED"


@pytest.mark.parametrize(
    "command",
    [
        "git commit -am x",
        "git commit -a -m x",
        "git commit --all -m x",
        "git add . && git commit -m x",
    ],
)
def test_unstaged_secret_is_found_when_commit_includes_worktree(
    command: str, tmp_path: Path
) -> None:
    for args in (
        ["init", "-q"],
        ["config", "user.email", "t@example.com"],
        ["config", "user.name", "t"],
    ):
        subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True)
    (tmp_path / "notes.txt").write_text("hello\n", encoding="utf-8")
    subprocess.run(["git", "add", "notes.txt"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=tmp_path, check=True)
    (tmp_path / "notes.txt").write_text("value = " + DUMMY + "\n", encoding="utf-8")

    inp = HookInput("PreToolUse", HostId.CLAUDE, "Bash", command, (), tmp_path, {})
    outcome = evaluate(inp, policy=Policy())

    assert outcome.decision == HookDecision.DENY
    assert outcome.reason_code == "SECRET_IN_STAGED_DIFF"


def test_plain_commit_ignores_unstaged_changes(tmp_path: Path) -> None:
    for args in (
        ["init", "-q"],
        ["config", "user.email", "t@example.com"],
        ["config", "user.name", "t"],
    ):
        subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True)
    (tmp_path / "notes.txt").write_text("hello\n", encoding="utf-8")
    subprocess.run(["git", "add", "notes.txt"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=tmp_path, check=True)
    (tmp_path / "notes.txt").write_text("value = " + DUMMY + "\n", encoding="utf-8")

    inp = HookInput("PreToolUse", HostId.CLAUDE, "Bash", "git commit -m x", (), tmp_path, {})
    outcome = evaluate(inp, policy=Policy())

    assert outcome.decision == HookDecision.ALLOW


def test_commit_all_without_head_scans_worktree_diff(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / "n.txt").write_text("a\n", encoding="utf-8")
    subprocess.run(["git", "add", "-N", "n.txt"], cwd=tmp_path, check=True)
    (tmp_path / "n.txt").write_text("v = " + DUMMY + "\n", encoding="utf-8")

    inp = HookInput("PreToolUse", HostId.CLAUDE, "Bash", "git commit -am x", (), tmp_path, {})
    outcome = evaluate(inp, policy=Policy())

    assert outcome.reason_code == "SECRET_IN_STAGED_DIFF"


@pytest.mark.parametrize("command", ["git -C other commit -m x", "cd other && git commit -m x"])
def test_commit_outside_cwd_asks(command: str, tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)

    inp = HookInput("PreToolUse", HostId.CLAUDE, "Bash", command, (), tmp_path, {})
    outcome = evaluate(inp, policy=Policy())

    assert outcome.decision == HookDecision.ASK
    assert outcome.reason_code == "COMMIT_OUTSIDE_CWD"
