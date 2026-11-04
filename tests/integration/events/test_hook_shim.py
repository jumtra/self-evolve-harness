import os
import subprocess
from pathlib import Path

import seh

TEMPLATES = Path(seh.__file__).parent / "templates" / "hooks"


def test_shim_passes_through_silently_when_seh_is_absent(tmp_path: Path) -> None:
    empty_bin = tmp_path / "bin"
    empty_bin.mkdir()

    result = subprocess.run(
        ["/bin/sh", str(TEMPLATES / "seh-hook.sh"), "PreToolUse"],
        env={"PATH": str(empty_bin)},
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert result.stderr == ""


def test_shim_announces_missing_seh_on_session_start(tmp_path: Path) -> None:
    empty_bin = tmp_path / "bin"
    empty_bin.mkdir()

    result = subprocess.run(
        ["/bin/sh", str(TEMPLATES / "seh-hook.sh"), "SessionStart"],
        env={"PATH": str(empty_bin)},
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "警告: seh が未導入のため Hook を通過させます" in result.stderr
    assert "uv tool install git+https://github.com/jumtra/self-evolve-harness" in result.stderr


def test_shim_propagates_exit_code_from_seh_on_path(tmp_path: Path) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_seh = fake_bin / "seh"
    fake_seh.write_text('#!/bin/sh\necho "args: $*" >&2\nexit 2\n', encoding="utf-8")
    os.chmod(fake_seh, 0o755)

    result = subprocess.run(
        ["/bin/sh", str(TEMPLATES / "seh-hook.sh"), "PreToolUse", "--host", "claude"],
        env={"PATH": str(fake_bin)},
        capture_output=True,
        text=True,
    )

    assert result.returncode == 2
    assert "args: hook PreToolUse --host claude" in result.stderr


def test_opencode_plugin_template_contains_required_contract() -> None:
    source = (TEMPLATES / "seh-guard.ts").read_text(encoding="utf-8")

    assert "tool.execute.before" in source
    assert '"hook", "PreToolUse", "--host", "opencode"' in source
    assert "JSON.stringify" in source
    assert "throw new Error" in source
    assert "console.warn" in source
    assert "ENOENT" in source
