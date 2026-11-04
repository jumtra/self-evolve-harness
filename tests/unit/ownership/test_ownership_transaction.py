import json
import os
from pathlib import Path

import pytest

from seh.ownership import SymlinkConflict, Transaction, recover_incomplete, rollback


def test_commit_applies_changes_and_marks_journal_committed(tmp_path: Path) -> None:
    (tmp_path / "old.txt").write_bytes(b"bye")

    with Transaction(tmp_path) as tx:
        tx.write("new/a.txt", b"hello")
        tx.delete("old.txt")
        snapshot_id = tx.snapshot_id

    journal = json.loads((tmp_path / ".harness/backups" / snapshot_id / "journal.json").read_text())
    assert (tmp_path / "new/a.txt").read_bytes() == b"hello"
    assert not (tmp_path / "old.txt").exists()
    assert journal["status"] == "committed"


def test_exception_rolls_back_create_modify_delete_and_symlink(tmp_path: Path) -> None:
    (tmp_path / "mod.txt").write_bytes(b"orig")
    (tmp_path / "gone.txt").write_bytes(b"keep me")
    (tmp_path / "target-a").write_bytes(b"a")
    (tmp_path / "link").symlink_to("target-a")

    with pytest.raises(RuntimeError, match="boom"), Transaction(tmp_path) as tx:
        tx.write("created/new.txt", b"n")
        tx.write("mod.txt", b"changed")
        tx.delete("gone.txt")
        tx.replace_symlink("link", "other")
        raise RuntimeError("boom")

    assert not (tmp_path / "created").exists()
    assert (tmp_path / "mod.txt").read_bytes() == b"orig"
    assert (tmp_path / "gone.txt").read_bytes() == b"keep me"
    assert os.readlink(tmp_path / "link") == "target-a"


def test_rollback_after_commit_restores_previous_state(tmp_path: Path) -> None:
    (tmp_path / "mod.txt").write_bytes(b"orig")
    with Transaction(tmp_path) as tx:
        tx.write("mod.txt", b"changed")
        tx.write("added.txt", b"x")
        snapshot_id = tx.snapshot_id

    restored = rollback(tmp_path, snapshot_id)

    assert sorted(restored) == ["added.txt", "mod.txt"]
    assert (tmp_path / "mod.txt").read_bytes() == b"orig"
    assert not (tmp_path / "added.txt").exists()


def test_custom_snapshot_root_is_used(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    snaps = tmp_path / "snaps"

    with Transaction(root, snapshot_root=snaps) as tx:
        tx.write("a.txt", b"x")
        snapshot_id = tx.snapshot_id

    assert (snaps / snapshot_id / "journal.json").is_file()
    assert not (root / ".harness").exists()


def test_replace_symlink_creates_link_and_rollback_removes_it(tmp_path: Path) -> None:
    with Transaction(tmp_path) as tx:
        tx.replace_symlink("AGENTS.md", "CLAUDE.md")
        snapshot_id = tx.snapshot_id

    assert os.readlink(tmp_path / "AGENTS.md") == "CLAUDE.md"
    rollback(tmp_path, snapshot_id)
    assert not (tmp_path / "AGENTS.md").is_symlink()


def test_remove_symlink_deletes_link_and_rollback_restores_it(tmp_path: Path) -> None:
    (tmp_path / "link").symlink_to("somewhere")
    with Transaction(tmp_path) as tx:
        tx.remove_symlink("link")
        snapshot_id = tx.snapshot_id

    assert not (tmp_path / "link").is_symlink()
    rollback(tmp_path, snapshot_id)
    assert os.readlink(tmp_path / "link") == "somewhere"


def test_recover_incomplete_restores_in_progress_transaction(tmp_path: Path) -> None:
    (tmp_path / "mod.txt").write_bytes(b"orig")
    tx = Transaction(tmp_path)
    tx.write("mod.txt", b"changed")
    tx.write("added.txt", b"x")

    recovered = recover_incomplete(tmp_path)

    assert recovered == [tx.snapshot_id]
    assert (tmp_path / "mod.txt").read_bytes() == b"orig"
    assert not (tmp_path / "added.txt").exists()
    assert recover_incomplete(tmp_path) == []


def test_recover_incomplete_ignores_committed_transactions(tmp_path: Path) -> None:
    with Transaction(tmp_path) as tx:
        tx.write("a.txt", b"x")

    recovered = recover_incomplete(tmp_path)

    assert recovered == []
    assert (tmp_path / "a.txt").read_bytes() == b"x"


@pytest.mark.parametrize("bad", ["../escape.txt", "/etc/passwd", "a/../../x", ""])
def test_paths_outside_root_are_rejected(tmp_path: Path, bad: str) -> None:
    with Transaction(tmp_path) as tx, pytest.raises(ValueError):
        tx.write(bad, b"x")


def test_write_through_ancestor_symlink_is_symlink_conflict(tmp_path: Path) -> None:
    (tmp_path / "real").mkdir()
    (tmp_path / "alias").symlink_to("real")

    with Transaction(tmp_path) as tx, pytest.raises(SymlinkConflict):
        tx.write("alias/a.txt", b"x")

    assert not (tmp_path / "real" / "a.txt").exists()


def test_write_to_symlink_itself_is_symlink_conflict(tmp_path: Path) -> None:
    (tmp_path / "real.txt").write_bytes(b"orig")
    (tmp_path / "link.txt").symlink_to("real.txt")

    with Transaction(tmp_path) as tx, pytest.raises(SymlinkConflict):
        tx.write("link.txt", b"x")

    assert (tmp_path / "real.txt").read_bytes() == b"orig"


def test_delete_symlink_via_delete_is_symlink_conflict(tmp_path: Path) -> None:
    (tmp_path / "link.txt").symlink_to("real.txt")

    with Transaction(tmp_path) as tx, pytest.raises(SymlinkConflict):
        tx.delete("link.txt")

    assert (tmp_path / "link.txt").is_symlink()
