import asyncio
import subprocess
from pathlib import Path

import pytest

from seh.runtime.worktree import WorktreeError, WorktreeManager


@pytest.fixture(autouse=True)
def git_identity(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("GIT_AUTHOR_NAME", "tester")
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", "tester@example.com")
    monkeypatch.setenv("GIT_COMMITTER_NAME", "tester")
    monkeypatch.setenv("GIT_COMMITTER_EMAIL", "tester@example.com")


def test_scope_violations_reports_paths_outside_allowlist(tmp_path: Path):
    manager = WorktreeManager(tmp_path, run_id="r1")

    violations = manager.scope_violations(
        ["src/app/main.py", "src/app/sub/deep.py", "docs/readme.md", "top.py"],
        ["src/**/*.py", "top.py"],
    )

    assert violations == ("docs/readme.md",)


def test_scope_violations_single_star_does_not_cross_directories(tmp_path: Path):
    manager = WorktreeManager(tmp_path, run_id="r1")

    violations = manager.scope_violations(["src/a.py", "src/sub/b.py"], ["src/*.py"])

    assert violations == ("src/sub/b.py",)


def test_scope_violations_always_rejects_git_dir_and_parent_traversal(tmp_path: Path):
    manager = WorktreeManager(tmp_path, run_id="r1")

    violations = manager.scope_violations(
        [".git/config", "src/../../etc/passwd", "sub/.git/hooks/pre-commit", "/abs/file"],
        ["**"],
    )

    assert violations == (
        ".git/config",
        "/abs/file",
        "src/../../etc/passwd",
        "sub/.git/hooks/pre-commit",
    )


@pytest.mark.parametrize("bad", ["../x", "a/b", "", "-x", "a b"])
async def test_create_rejects_unsafe_node_id(tmp_path: Path, bad: str):
    manager = WorktreeManager(tmp_path, run_id="r1")

    with pytest.raises(ValueError):
        await manager.create(bad, base="HEAD")


def test_constructor_rejects_unsafe_run_id(tmp_path: Path):
    with pytest.raises(ValueError):
        WorktreeManager(tmp_path, run_id="../evil")


async def test_base_commit_outside_git_repo_raises_not_a_git_repo(tmp_path: Path):
    manager = WorktreeManager(tmp_path, run_id="r1")

    with pytest.raises(WorktreeError) as exc:
        await manager.base_commit()

    assert exc.value.code == "NOT_A_GIT_REPO"


async def test_base_commit_with_uncommitted_change_raises_dirty_base(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    for argv in (["git", "init", "-b", "main"], ["git", "config", "commit.gpgsign", "false"]):
        subprocess.run(argv, cwd=repo, check=True, capture_output=True)
    (repo / "a.txt").write_text("one\n")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True)
    (repo / "a.txt").write_text("two\n")
    manager = WorktreeManager(repo, run_id="r1")

    with pytest.raises(WorktreeError) as exc:
        await manager.base_commit()

    assert exc.value.code == "DIRTY_BASE"


async def test_base_commit_ignores_files_under_harness_state(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True, capture_output=True)
    (repo / "a.txt").write_text("one\n")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "commit.gpgsign=false", "commit", "-m", "init"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    (repo / ".harness" / "state").mkdir(parents=True)
    (repo / ".harness" / "state" / "run.json").write_text("{}\n")
    expected = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()
    manager = WorktreeManager(repo, run_id="r1")

    head = await manager.base_commit()

    assert head == expected


async def test_changed_paths_reports_modify_delete_rename_add_and_respects_gitignore(
    tmp_path: Path,
):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True, capture_output=True)
    (repo / ".gitignore").write_text("*.log\n")
    (repo / "a.txt").write_text("alpha\n")
    (repo / "b.txt").write_text("bravo\n")
    (repo / "c.txt").write_text("charlie line one\ncharlie line two\ncharlie line three\n")
    (repo / "keep.txt").write_text("untouched\n")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "commit.gpgsign=false", "commit", "-m", "init"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    manager = WorktreeManager(repo, run_id="r1", root=tmp_path / "wt")
    base = await manager.base_commit()
    ws = await manager.create("n1", base=base)

    (ws.path / "a.txt").write_text("alpha changed\n")
    (ws.path / "b.txt").unlink()
    subprocess.run(["git", "mv", "c.txt", "c2.txt"], cwd=ws.path, check=True, capture_output=True)
    (ws.path / "new.txt").write_text("brand new\n")
    (ws.path / "debug.log").write_text("ignored\n")
    changed = await manager.changed_paths(ws)

    assert ws.base_commit == base
    assert ws.branch == "seh/r1/n1"
    assert changed == ("a.txt", "b.txt", "c.txt", "c2.txt", "new.txt")


async def test_commit_unit_without_changes_returns_base_commit(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True, capture_output=True)
    (repo / "a.txt").write_text("alpha\n")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "commit.gpgsign=false", "commit", "-m", "init"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    manager = WorktreeManager(repo, run_id="r1", root=tmp_path / "wt")
    base = await manager.base_commit()
    ws = await manager.create("n1", base=base)

    result = await manager.commit_unit(ws, "nothing")

    assert result == base


async def test_commit_unit_commits_changes_with_fixed_author(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True, capture_output=True)
    (repo / "a.txt").write_text("alpha\n")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "commit.gpgsign=false", "commit", "-m", "init"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    manager = WorktreeManager(repo, run_id="r1", root=tmp_path / "wt")
    base = await manager.base_commit()
    ws = await manager.create("n1", base=base)
    (ws.path / "a.txt").write_text("alpha changed\n")
    (ws.path / "added.txt").write_text("added\n")

    commit = await manager.commit_unit(ws, "unit n1")

    author = subprocess.run(
        ["git", "log", "-1", "--format=%an <%ae>|%cn <%ce>|%s", commit],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert commit != base
    assert author == "seh <seh@localhost>|seh <seh@localhost>|unit n1"


async def test_integrate_merges_disjoint_units_without_touching_repo_worktree(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True, capture_output=True)
    (repo / "a.txt").write_text("alpha\n")
    (repo / "b.txt").write_text("bravo\n")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "commit.gpgsign=false", "commit", "-m", "init"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    manager = WorktreeManager(repo, run_id="r1", root=tmp_path / "wt")
    base = await manager.base_commit()
    ws_a = await manager.create("a", base=base)
    ws_b = await manager.create("b", base=base)
    (ws_a.path / "a.txt").write_text("alpha by a\n")
    (ws_b.path / "b.txt").write_text("bravo by b\n")
    await manager.commit_unit(ws_a, "unit a")
    await manager.commit_unit(ws_b, "unit b")

    result = await manager.integrate([ws_a, ws_b], target_branch="seh/integration")

    show_a = subprocess.run(
        ["git", "show", "seh/integration:a.txt"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    show_b = subprocess.run(
        ["git", "show", "seh/integration:b.txt"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    head_after = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()
    status = subprocess.run(
        ["git", "status", "--porcelain"], cwd=repo, check=True, capture_output=True, text=True
    ).stdout
    target_tip = subprocess.run(
        ["git", "rev-parse", "seh/integration"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert result.merged == ("a", "b")
    assert result.conflicts == ()
    assert result.head == target_tip
    assert show_a == "alpha by a\n"
    assert show_b == "bravo by b\n"
    assert head_after == base
    assert (repo / "a.txt").read_text() == "alpha\n"
    assert (repo / "b.txt").read_text() == "bravo\n"
    assert status == ""


async def test_integrate_reports_conflict_aborts_merge_and_continues(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True, capture_output=True)
    (repo / "shared.txt").write_text("line one\nline two\nline three\n")
    (repo / "other.txt").write_text("other\n")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "commit.gpgsign=false", "commit", "-m", "init"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    manager = WorktreeManager(repo, run_id="r1", root=tmp_path / "wt")
    base = await manager.base_commit()
    ws_a = await manager.create("a", base=base)
    ws_b = await manager.create("b", base=base)
    ws_c = await manager.create("c", base=base)
    (ws_a.path / "shared.txt").write_text("line one\nline two by a\nline three\n")
    (ws_b.path / "shared.txt").write_text("line one\nline two by b\nline three\n")
    (ws_c.path / "other.txt").write_text("other by c\n")
    await manager.commit_unit(ws_a, "unit a")
    await manager.commit_unit(ws_b, "unit b")
    await manager.commit_unit(ws_c, "unit c")

    result = await manager.integrate([ws_a, ws_b, ws_c], target_branch="seh/integration")

    integration_status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=tmp_path / "wt" / "_integration",
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    shared = subprocess.run(
        ["git", "show", "seh/integration:shared.txt"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    other = subprocess.run(
        ["git", "show", "seh/integration:other.txt"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert result.merged == ("a", "c")
    assert result.conflicts == (("b", ("shared.txt",)),)
    assert integration_status == ""
    assert shared == "line one\nline two by a\nline three\n"
    assert other == "other by c\n"


async def test_parallel_units_do_not_leak_changes_into_each_other(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True, capture_output=True)
    (repo / "seed.txt").write_text("seed\n")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "commit.gpgsign=false", "commit", "-m", "init"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    manager = WorktreeManager(repo, run_id="r1", root=tmp_path / "wt")
    base = await manager.base_commit()

    async def work(node_id: str):
        ws = await manager.create(node_id, base=base)
        (ws.path / f"{node_id}.txt").write_text(f"made by {node_id}\n")
        await manager.commit_unit(ws, f"unit {node_id}")
        return ws

    units = await asyncio.gather(work("n1"), work("n2"), work("n3"))

    for ws in units:
        changed = await manager.changed_paths(ws)
        present = sorted(p.name for p in ws.path.glob("n*.txt"))
        assert changed == (f"{ws.node_id}.txt",)
        assert present == [f"{ws.node_id}.txt"]
    assert not list(repo.glob("n*.txt"))


async def test_create_twice_for_same_node_raises_worktree_exists(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True, capture_output=True)
    (repo / "a.txt").write_text("alpha\n")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "commit.gpgsign=false", "commit", "-m", "init"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    manager = WorktreeManager(repo, run_id="r1", root=tmp_path / "wt")
    base = await manager.base_commit()
    await manager.create("n1", base=base)

    with pytest.raises(WorktreeError) as exc:
        await manager.create("n1", base=base)

    assert exc.value.code == "WORKTREE_EXISTS"


async def test_cleanup_removes_worktrees_and_branches(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True, capture_output=True)
    (repo / "a.txt").write_text("alpha\n")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "commit.gpgsign=false", "commit", "-m", "init"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    manager = WorktreeManager(repo, run_id="r1", root=tmp_path / "wt")
    base = await manager.base_commit()
    ws = await manager.create("n1", base=base)
    (ws.path / "a.txt").write_text("alpha changed\n")
    await manager.commit_unit(ws, "unit n1")
    await manager.integrate([ws], target_branch="seh/integration")

    await manager.cleanup()
    await manager.cleanup()

    listing = subprocess.run(
        ["git", "worktree", "list", "--porcelain"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    branches = subprocess.run(
        ["git", "branch", "--list", "seh/r1/*"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert str(tmp_path / "wt") not in listing
    assert not ws.path.exists()
    assert branches == ""


async def test_cleanup_keep_branches_leaves_unit_branch(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True, capture_output=True)
    (repo / "a.txt").write_text("alpha\n")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "commit.gpgsign=false", "commit", "-m", "init"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    manager = WorktreeManager(repo, run_id="r1", root=tmp_path / "wt")
    base = await manager.base_commit()
    ws = await manager.create("n1", base=base)

    await manager.cleanup(keep_branches=True)

    branches = subprocess.run(
        ["git", "branch", "--list", "seh/r1/*"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert not ws.path.exists()
    assert "seh/r1/n1" in branches
