import subprocess
from pathlib import Path

from seh.authoring.classify import FileChange, changes_from_git


def test_changes_from_git_reports_add_modify_delete(tmp_path: Path) -> None:
    git = ["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false"]
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / "CLAUDE.md").write_text("old\n", encoding="utf-8")
    (tmp_path / "AGENTS.md").write_text("keep\n", encoding="utf-8")
    subprocess.run([*git, "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run([*git, "commit", "-q", "-m", "base"], cwd=tmp_path, check=True)
    (tmp_path / "CLAUDE.md").write_text("new\n", encoding="utf-8")
    (tmp_path / "AGENTS.md").unlink()
    (tmp_path / ".claude" / "rules").mkdir(parents=True)
    (tmp_path / ".claude" / "rules" / "r.md").write_text("rule\n", encoding="utf-8")
    subprocess.run([*git, "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run([*git, "commit", "-q", "-m", "head"], cwd=tmp_path, check=True)

    changes = changes_from_git(tmp_path, "HEAD~1", "HEAD")

    assert sorted(changes, key=lambda c: c.path) == [
        FileChange(".claude/rules/r.md", None, "rule\n"),
        FileChange("AGENTS.md", "keep\n", None),
        FileChange("CLAUDE.md", "old\n", "new\n"),
    ]


def test_changes_from_git_treats_rename_as_delete_plus_add(tmp_path: Path) -> None:
    git = ["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false"]
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / "CLAUDE.md").write_text("same content here\n", encoding="utf-8")
    subprocess.run([*git, "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run([*git, "commit", "-q", "-m", "base"], cwd=tmp_path, check=True)
    subprocess.run([*git, "mv", "CLAUDE.md", "AGENTS.md"], cwd=tmp_path, check=True)
    subprocess.run([*git, "commit", "-q", "-m", "mv"], cwd=tmp_path, check=True)

    changes = changes_from_git(tmp_path, "HEAD~1", "HEAD")

    assert sorted(changes, key=lambda c: c.path) == [
        FileChange("AGENTS.md", None, "same content here\n"),
        FileChange("CLAUDE.md", "same content here\n", None),
    ]


def test_changes_from_git_with_head_none_reads_worktree_including_untracked(
    tmp_path: Path,
) -> None:
    git = ["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false"]
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / "CLAUDE.md").write_text("committed\n", encoding="utf-8")
    subprocess.run([*git, "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run([*git, "commit", "-q", "-m", "base"], cwd=tmp_path, check=True)
    (tmp_path / "CLAUDE.md").write_text("dirty\n", encoding="utf-8")
    (tmp_path / "AGENTS.md").write_text("untracked\n", encoding="utf-8")

    changes = changes_from_git(tmp_path, "HEAD", None)

    assert sorted(changes, key=lambda c: c.path) == [
        FileChange("AGENTS.md", None, "untracked\n"),
        FileChange("CLAUDE.md", "committed\n", "dirty\n"),
    ]
