import hashlib
from pathlib import Path

from seh.contracts import ChangeAction, PlannedChange
from seh.ownership import FileStatus, OwnershipManifest, classify_change


def test_missing_file_is_new(tmp_path: Path) -> None:
    change = PlannedChange("a.md", ChangeAction.CREATE, b"new", "r", "seh")

    status = classify_change(tmp_path, OwnershipManifest.load(tmp_path), change)

    assert status == FileStatus.NEW


def test_disk_equal_to_proposed_is_unchanged(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_bytes(b"same")
    change = PlannedChange("a.md", ChangeAction.UPDATE, b"same", "r", "seh")

    status = classify_change(tmp_path, OwnershipManifest.load(tmp_path), change)

    assert status == FileStatus.UNCHANGED


def test_disk_equal_to_recorded_hash_is_clean_update(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_bytes(b"old")
    manifest = OwnershipManifest.load(tmp_path)
    manifest.record("a.md", hashlib.sha256(b"old").hexdigest(), "host:claude", "2.0.0")
    change = PlannedChange("a.md", ChangeAction.UPDATE, b"new", "r", "seh")

    status = classify_change(tmp_path, manifest, change)

    assert status == FileStatus.CLEAN_UPDATE


def test_disk_differs_from_recorded_hash_is_user_modified(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_bytes(b"edited by user")
    manifest = OwnershipManifest.load(tmp_path)
    manifest.record("a.md", hashlib.sha256(b"old").hexdigest(), "host:claude", "2.0.0")
    change = PlannedChange("a.md", ChangeAction.UPDATE, b"new", "r", "seh")

    status = classify_change(tmp_path, manifest, change)

    assert status == FileStatus.USER_MODIFIED


def test_unmanaged_existing_file_is_user_owned(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_bytes(b"mine")
    change = PlannedChange("a.md", ChangeAction.CREATE, b"new", "r", "seh")

    status = classify_change(tmp_path, OwnershipManifest.load(tmp_path), change)

    assert status == FileStatus.USER_OWNED


def test_unmanaged_file_matching_base_sha256_is_clean_update(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_bytes(b"v1 content")
    change = PlannedChange("a.md", ChangeAction.UPDATE, b"new", "r", "seh")

    status = classify_change(
        tmp_path,
        OwnershipManifest.load(tmp_path),
        change,
        base_sha256=hashlib.sha256(b"v1 content").hexdigest(),
    )

    assert status == FileStatus.CLEAN_UPDATE


def test_unmanaged_file_not_matching_base_sha256_is_user_owned(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_bytes(b"other")
    change = PlannedChange("a.md", ChangeAction.UPDATE, b"new", "r", "seh")

    status = classify_change(
        tmp_path,
        OwnershipManifest.load(tmp_path),
        change,
        base_sha256=hashlib.sha256(b"v1 content").hexdigest(),
    )

    assert status == FileStatus.USER_OWNED


def test_ancestor_symlink_is_symlink_conflict(tmp_path: Path) -> None:
    (tmp_path / "real").mkdir()
    (tmp_path / "real" / "a.md").write_bytes(b"x")
    (tmp_path / "alias").symlink_to("real")
    change = PlannedChange("alias/a.md", ChangeAction.UPDATE, b"new", "r", "seh")

    status = classify_change(tmp_path, OwnershipManifest.load(tmp_path), change)

    assert status == FileStatus.SYMLINK_CONFLICT


def test_unmanaged_symlink_to_outside_repo_is_symlink_conflict(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    outside = tmp_path / "outside.md"
    outside.write_bytes(b"x")
    (root / "a.md").symlink_to(outside)
    change = PlannedChange("a.md", ChangeAction.UPDATE, b"new", "r", "seh")

    status = classify_change(root, OwnershipManifest.load(root), change)

    assert status == FileStatus.SYMLINK_CONFLICT


def test_managed_symlink_with_matching_target_is_clean_update(tmp_path: Path) -> None:
    (tmp_path / "old.md").write_bytes(b"x")
    (tmp_path / "link").symlink_to("old.md")
    manifest = OwnershipManifest.load(tmp_path)
    manifest.record("link", "", "host:claude", "2.0.0", kind="symlink", link_target="old.md")
    change = PlannedChange("link", ChangeAction.LINK, b"new.md", "r", "seh")

    status = classify_change(tmp_path, manifest, change)

    assert status == FileStatus.CLEAN_UPDATE
