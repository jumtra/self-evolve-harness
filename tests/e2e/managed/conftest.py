from __future__ import annotations

import subprocess
from pathlib import Path

import pytest


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """初期コミット済みの使い捨て git repo。state/artifacts は ignore 済み。"""
    root = tmp_path / "repo"
    (root / ".harness").mkdir(parents=True)
    (root / ".gitignore").write_text(".harness/state/\n.harness/artifacts/\n")
    (root / ".harness" / "config.toml").write_text(
        '[runtime.security]\ncommand_allowlist = ["python3"]\n'
    )
    (root / "shared.txt").write_text("base\n")
    identity = ["-c", "user.name=t", "-c", "user.email=t@example.com", "-c", "commit.gpgsign=false"]
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=root, check=True)
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    subprocess.run(["git", *identity, "commit", "-q", "-m", "init"], cwd=root, check=True)
    return root
