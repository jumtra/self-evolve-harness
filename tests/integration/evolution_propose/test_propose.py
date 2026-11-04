import subprocess
from pathlib import Path

import pytest

from seh.evolution.propose import ProposalError, propose


@pytest.mark.parametrize(
    "path",
    [
        ".harness/state/evolution/candidate.json",
        ".harness/evolution/promotions/id.json",
        ".harness/knowledge/verified_constraints.jsonl",
    ],
)
def test_candidate_cannot_write_evolution_evidence(path):
    from seh.evolution.propose import ProposalError, _check_path

    with pytest.raises(ProposalError):
        _check_path(path)


def git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    git(tmp_path, "init")
    git(tmp_path, "config", "user.name", "Test")
    git(tmp_path, "config", "user.email", "test@example.org")
    (tmp_path / "file.txt").write_text("original")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-m", "initial")
    return tmp_path


@pytest.mark.asyncio
async def test_candidate_is_isolated(repo: Path) -> None:
    candidate = await propose(
        repo, run_id="run1", candidate_id="candidate", changes={"file.txt": "new"}
    )
    assert (candidate.workspace.path / "file.txt").read_text() == "new"
    assert (repo / "file.txt").read_text() == "original"
    assert candidate.changed_paths == ("file.txt",)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path", ["src/seh/policy.py", ".harness/config.toml", "../outside", "/tmp/outside"]
)
async def test_protected_and_escape_paths_are_rejected(repo: Path, path: str) -> None:
    with pytest.raises(ProposalError):
        await propose(repo, run_id="run1", candidate_id="candidate", changes={path: "bad"})
    assert not (repo / ".harness/state/worktrees/run1/candidate").exists()


@pytest.mark.asyncio
async def test_symlink_parent_is_rejected(repo: Path, tmp_path: Path) -> None:
    (repo / "link").symlink_to(tmp_path, target_is_directory=True)
    git(repo, "add", "link")
    git(repo, "commit", "-m", "link")
    with pytest.raises(ProposalError):
        await propose(
            repo, run_id="run1", candidate_id="candidate", changes={"link/outside": "bad"}
        )
    assert not (tmp_path / "outside").exists()
