from pathlib import Path

import pytest

from seh.contracts import HostId
from seh.events import HookDecision, HookInput, evaluate
from seh.policy import Policy


@pytest.mark.parametrize(
    "command",
    [
        "r" + "m -" + "rf /",
        "r" + "m -" + "rf ~",
        "su" + "do r" + "m -" + "rf $HOME/",
        "r" + "m -" + "rf /*",
        "mkfs.ext4 /dev/sda1",
        "dd if=/dev/zero of=/dev/sda bs=1M",
        ":(){ :|:& };:",
    ],
)
def test_catastrophic_commands_are_denied(command: str, tmp_path: Path) -> None:
    inp = HookInput("PreToolUse", HostId.CLAUDE, "Bash", command, (), tmp_path, {})

    outcome = evaluate(inp, policy=Policy())

    assert outcome.decision == HookDecision.DENY
    assert outcome.reason_code == "CATASTROPHIC_COMMAND"


@pytest.mark.parametrize(
    "command", ["rm -rf build", "rm -rf ./work-dir", "git push --force origin x"]
)
def test_r2_commands_ask(command: str, tmp_path: Path) -> None:
    inp = HookInput("PreToolUse", HostId.CLAUDE, "Bash", command, (), tmp_path, {})

    outcome = evaluate(inp, policy=Policy())

    assert outcome.decision == HookDecision.ASK
    assert outcome.reason_code == "R2_REQUIRES_APPROVAL"


@pytest.mark.parametrize("command", ["git push origin main", "gh pr create --fill"])
def test_external_effect_commands_ask(command: str, tmp_path: Path) -> None:
    inp = HookInput("PreToolUse", HostId.CLAUDE, "Bash", command, (), tmp_path, {})

    outcome = evaluate(inp, policy=Policy())

    assert outcome.decision == HookDecision.ASK
    assert outcome.reason_code == "EXTERNAL_EFFECT_REQUIRES_APPROVAL"


@pytest.mark.parametrize("command", ["ls -la", "uv run pytest -q", "git status", "rm file.txt"])
def test_ordinary_commands_are_allowed(command: str, tmp_path: Path) -> None:
    inp = HookInput("PreToolUse", HostId.CLAUDE, "Bash", command, (), tmp_path, {})

    outcome = evaluate(inp, policy=Policy())

    assert outcome.decision == HookDecision.ALLOW


@pytest.mark.parametrize(
    "path",
    [
        ".env",
        ".env.local",
        "certs/server.pem",
        "keys/id.key",
        "config/my_credentials.json",
        "app/Secrets.yaml",
    ],
)
def test_sensitive_files_are_denied(path: str, tmp_path: Path) -> None:
    inp = HookInput("PreToolUse", HostId.CLAUDE, "Write", None, (path,), tmp_path, {})

    outcome = evaluate(inp, policy=Policy())

    assert outcome.decision == HookDecision.DENY
    assert outcome.reason_code == "SENSITIVE_FILE"


@pytest.mark.parametrize(
    "path",
    [
        ".eslintrc.json",
        "eslint.config.js",
        ".prettierrc",
        "prettier.config.cjs",
        "biome.json",
        "biome.jsonc",
        "ruff.toml",
        "sub/.ruff.toml",
        "pyrightconfig.json",
        "mypy.ini",
        ".flake8",
        "tsconfig.json",
        "tsconfig.build.json",
        ".golangci.yml",
        "rustfmt.toml",
        "clippy.toml",
        ".editorconfig",
    ],
)
def test_tool_config_files_are_denied(path: str, tmp_path: Path) -> None:
    inp = HookInput("PreToolUse", HostId.CLAUDE, "Edit", None, (path,), tmp_path, {})

    outcome = evaluate(inp, policy=Policy())

    assert outcome.decision == HookDecision.DENY
    assert outcome.reason_code == "PROTECTED_TOOL_CONFIG"


def test_pyproject_is_not_a_protected_tool_config(tmp_path: Path) -> None:
    inp = HookInput("PreToolUse", HostId.CLAUDE, "Edit", None, ("pyproject.toml",), tmp_path, {})

    outcome = evaluate(inp, policy=Policy())

    assert outcome.decision == HookDecision.ALLOW


@pytest.mark.parametrize(
    "path", [".claude/settings.json", ".github/workflows/ci.yml", ".harness/config.toml"]
)
def test_protected_paths_ask(path: str, tmp_path: Path) -> None:
    inp = HookInput("PreToolUse", HostId.CLAUDE, "Write", None, (path,), tmp_path, {})

    outcome = evaluate(inp, policy=Policy())

    assert outcome.decision == HookDecision.ASK
    assert outcome.reason_code == "PROTECTED_PATH"


def test_absolute_path_inside_cwd_is_judged_relative_to_cwd(tmp_path: Path) -> None:
    target = str(tmp_path / ".claude" / "settings.json")
    inp = HookInput("PreToolUse", HostId.CLAUDE, "Write", None, (target,), tmp_path, {})

    outcome = evaluate(inp, policy=Policy())

    assert outcome.reason_code == "PROTECTED_PATH"


def test_ordinary_source_edit_is_allowed(tmp_path: Path) -> None:
    inp = HookInput("PreToolUse", HostId.CLAUDE, "Edit", None, ("src/app.py",), tmp_path, {})

    outcome = evaluate(inp, policy=Policy())

    assert outcome.decision == HookDecision.ALLOW


def test_deny_wins_over_ask_among_multiple_paths(tmp_path: Path) -> None:
    paths = (".claude/settings.json", ".env")
    inp = HookInput("PreToolUse", HostId.CLAUDE, "MultiEdit", None, paths, tmp_path, {})

    outcome = evaluate(inp, policy=Policy())

    assert outcome.decision == HookDecision.DENY


@pytest.mark.parametrize("event", ["PostToolUse", "SessionStart", "Stop"])
def test_non_pretooluse_events_are_always_allowed(event: str, tmp_path: Path) -> None:
    command = "r" + "m -" + "rf /"
    inp = HookInput(event, HostId.CLAUDE, "Bash", command, (), tmp_path, {})

    outcome = evaluate(inp, policy=Policy())

    assert outcome.decision == HookDecision.ALLOW
