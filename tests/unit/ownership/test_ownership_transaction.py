import json
import os
import socket
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from seh import ownership
from seh.ownership import (
    CorruptJournal,
    SymlinkConflict,
    Transaction,
    recover_incomplete,
    rollback,
)


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
    dead = subprocess.Popen([sys.executable, "-c", "pass"])
    dead.wait()
    journal_path = tmp_path / ".harness/backups" / tx.snapshot_id / "journal.json"
    journal = json.loads(journal_path.read_text())
    journal["pid"] = dead.pid
    journal_path.write_text(json.dumps(journal))

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


@pytest.mark.parametrize(
    "bad", ["../x", "abc", "20260101T000000Z-zzzzzz", "20260101T000000Z-abc12/.."]
)
def test_rollback_rejects_malformed_snapshot_id(tmp_path: Path, bad: str) -> None:
    with pytest.raises(ValueError, match="snapshot_id"):
        rollback(tmp_path, bad)


def test_rollback_rejects_backup_path_traversal_and_restores_nothing(tmp_path: Path) -> None:
    (tmp_path / "mod.txt").write_bytes(b"orig")
    (tmp_path / "secret.txt").write_bytes(b"secret")
    with Transaction(tmp_path) as tx:
        tx.write("mod.txt", b"changed")
        snapshot_id = tx.snapshot_id
    journal_path = tmp_path / ".harness/backups" / snapshot_id / "journal.json"
    journal = json.loads(journal_path.read_text())
    journal["entries"][0]["backup"] = "../../../secret.txt"
    journal_path.write_text(json.dumps(journal))

    with pytest.raises(CorruptJournal):
        rollback(tmp_path, snapshot_id)

    assert (tmp_path / "mod.txt").read_bytes() == b"changed"


def test_rollback_rejects_created_dirs_outside_root(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    root = tmp_path / "repo"
    root.mkdir()
    with Transaction(root) as tx:
        tx.write("a.txt", b"x")
        snapshot_id = tx.snapshot_id
    journal_path = root / ".harness/backups" / snapshot_id / "journal.json"
    journal = json.loads(journal_path.read_text())
    journal["entries"][0]["created_dirs"] = ["../outside"]
    journal_path.write_text(json.dumps(journal))

    with pytest.raises(CorruptJournal):
        rollback(root, snapshot_id)

    assert outside.is_dir()


def test_rollback_rejects_entry_path_outside_root(tmp_path: Path) -> None:
    with Transaction(tmp_path) as tx:
        tx.write("a.txt", b"x")
        snapshot_id = tx.snapshot_id
    journal_path = tmp_path / ".harness/backups" / snapshot_id / "journal.json"
    journal = json.loads(journal_path.read_text())
    journal["entries"][0]["path"] = "../evil.txt"
    journal_path.write_text(json.dumps(journal))

    with pytest.raises(CorruptJournal):
        rollback(tmp_path, snapshot_id)


def test_rollback_masks_journal_mode_to_permission_bits(tmp_path: Path) -> None:
    (tmp_path / "mod.txt").write_bytes(b"orig")
    with Transaction(tmp_path) as tx:
        tx.write("mod.txt", b"changed")
        snapshot_id = tx.snapshot_id
    journal_path = tmp_path / ".harness/backups" / snapshot_id / "journal.json"
    journal = json.loads(journal_path.read_text())
    journal["entries"][0]["mode"] = 0o4755
    journal_path.write_text(json.dumps(journal))

    rollback(tmp_path, snapshot_id)

    assert (tmp_path / "mod.txt").stat().st_mode & 0o7777 == 0o755


def test_rollback_twice_does_not_overwrite_later_user_changes(tmp_path: Path) -> None:
    (tmp_path / "mod.txt").write_bytes(b"orig")
    with Transaction(tmp_path) as tx:
        tx.write("mod.txt", b"changed")
        snapshot_id = tx.snapshot_id
    rollback(tmp_path, snapshot_id)
    (tmp_path / "mod.txt").write_bytes(b"user edit")

    second = rollback(tmp_path, snapshot_id)

    assert second == []
    assert (tmp_path / "mod.txt").read_bytes() == b"user edit"


def test_journal_records_pid_and_hostname(tmp_path: Path) -> None:
    tx = Transaction(tmp_path)

    journal = json.loads(
        (tmp_path / ".harness/backups" / tx.snapshot_id / "journal.json").read_text()
    )

    assert journal["pid"] == os.getpid()
    assert journal["hostname"] == socket.gethostname()


def test_backup_keeps_original_mode_and_snapshot_dir_is_private(tmp_path: Path) -> None:
    (tmp_path / "secret.txt").write_bytes(b"s")
    (tmp_path / "secret.txt").chmod(0o600)

    with Transaction(tmp_path) as tx:
        tx.write("secret.txt", b"t")
        snapshot_id = tx.snapshot_id

    snapshot = tmp_path / ".harness/backups" / snapshot_id
    assert (snapshot / "files/0").stat().st_mode & 0o777 == 0o600
    assert snapshot.stat().st_mode & 0o777 == 0o700


def test_commit_status_write_failure_raises_and_leaves_original_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "mod.txt").write_bytes(b"orig")
    real_write = ownership._write_journal

    def failing_write(directory: Path, journal: dict[str, Any]) -> None:
        if journal["status"] == "committed":
            raise OSError("disk full")
        real_write(directory, journal)

    monkeypatch.setattr(ownership, "_write_journal", failing_write)

    with pytest.raises(OSError, match="disk full"), Transaction(tmp_path) as tx:
        tx.write("mod.txt", b"changed")

    assert (tmp_path / "mod.txt").read_bytes() == b"orig"


def test_rollback_failure_keeps_original_exception_with_note(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def failing_rollback(*args: object, **kwargs: object) -> list[str]:
        raise OSError("rollback broke")

    monkeypatch.setattr(ownership, "rollback", failing_rollback)

    with pytest.raises(RuntimeError, match="boom") as info, Transaction(tmp_path) as tx:
        tx.write("a.txt", b"x")
        raise RuntimeError("boom")

    assert any("rollback broke" in note for note in info.value.__notes__)
