import hashlib
import json
from pathlib import Path

from seh.ownership import OwnershipManifest


def test_load_without_manifest_file_returns_empty_manifest(tmp_path: Path) -> None:
    manifest = OwnershipManifest.load(tmp_path)

    assert manifest.get("a.txt") is None


def test_save_then_load_round_trips_file_and_symlink_entries(tmp_path: Path) -> None:
    digest = hashlib.sha256(b"x").hexdigest()
    manifest = OwnershipManifest.load(tmp_path)
    manifest.record("b/file.md", digest, "host:claude", "2.0.0")
    manifest.record("link", "", "host:claude", "2.0.0", kind="symlink", link_target="b/file.md")

    manifest.save(tmp_path)
    loaded = OwnershipManifest.load(tmp_path)

    file_entry = loaded.get("b/file.md")
    link_entry = loaded.get("link")
    assert file_entry is not None and link_entry is not None
    assert (file_entry.sha256, file_entry.owner, file_entry.kind) == (digest, "seh", "file")
    assert (link_entry.kind, link_entry.link_target) == ("symlink", "b/file.md")


def test_save_writes_sorted_keys_two_space_indent_and_trailing_newline(tmp_path: Path) -> None:
    manifest = OwnershipManifest.load(tmp_path)
    manifest.record("z.txt", "aa", "host:claude", "2.0.0")
    manifest.record("a.txt", "bb", "host:codex", "2.0.0")

    manifest.save(tmp_path)

    text = (tmp_path / ".harness" / "ownership.json").read_text()
    data = json.loads(text)
    assert list(data["files"]) == ["a.txt", "z.txt"]
    assert data["schema_version"] == 1
    assert text == json.dumps(data, indent=2, sort_keys=True) + "\n"
    assert "link_target" not in data["files"]["a.txt"]


def test_forget_removes_entry(tmp_path: Path) -> None:
    manifest = OwnershipManifest.load(tmp_path)
    manifest.record("a.txt", "aa", "host:claude", "2.0.0")

    manifest.forget("a.txt")

    assert manifest.get("a.txt") is None
