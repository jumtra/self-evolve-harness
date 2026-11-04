import subprocess
from pathlib import Path

from seh.contracts import HostId
from seh.events import HookDecision, HookInput, evaluate
from seh.policy import Policy


def test_commit_with_secret_in_staged_diff_is_denied(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    dummy = "gh" + "p_" + "A1b2C3d4E5" * 4
    (tmp_path / "notes.txt").write_text("value = " + dummy + "\n", encoding="utf-8")
    subprocess.run(["git", "add", "notes.txt"], cwd=tmp_path, check=True)
    inp = HookInput("PreToolUse", HostId.CLAUDE, "Bash", "git commit -m wip", (), tmp_path, {})

    outcome = evaluate(inp, policy=Policy())

    assert outcome.decision == HookDecision.DENY
    assert outcome.reason_code == "SECRET_IN_STAGED_DIFF"
    assert dummy not in outcome.message


def test_commit_with_harmless_staged_diff_is_allowed(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / "notes.txt").write_text("hello world\n", encoding="utf-8")
    subprocess.run(["git", "add", "notes.txt"], cwd=tmp_path, check=True)
    inp = HookInput("PreToolUse", HostId.CLAUDE, "Bash", "git commit -m docs", (), tmp_path, {})

    outcome = evaluate(inp, policy=Policy())

    assert outcome.decision == HookDecision.ALLOW


def test_commit_chained_with_push_asks_when_diff_is_clean(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    command = "git commit -m x && git push origin main"
    inp = HookInput("PreToolUse", HostId.CLAUDE, "Bash", command, (), tmp_path, {})

    outcome = evaluate(inp, policy=Policy())

    assert outcome.decision == HookDecision.ASK
    assert outcome.reason_code == "EXTERNAL_EFFECT"
