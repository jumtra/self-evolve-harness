from pathlib import Path

from seh.ownership import atomic_write


def test_creates_parent_directories_and_writes_bytes(tmp_path: Path) -> None:
    target = tmp_path / "a" / "b" / "f.bin"

    atomic_write(target, b"\x00\x01")

    assert target.read_bytes() == b"\x00\x01"


def test_overwrite_leaves_no_temporary_files(tmp_path: Path) -> None:
    target = tmp_path / "f.txt"
    target.write_bytes(b"old")

    atomic_write(target, b"new")

    assert target.read_bytes() == b"new"
    assert [p.name for p in tmp_path.iterdir()] == ["f.txt"]


def test_mode_is_applied(tmp_path: Path) -> None:
    target = tmp_path / "run.sh"

    atomic_write(target, b"#!/bin/sh\n", mode=0o755)

    assert target.stat().st_mode & 0o777 == 0o755


def test_existing_mode_is_preserved_when_mode_is_omitted(tmp_path: Path) -> None:
    target = tmp_path / "run.sh"
    target.write_bytes(b"old")
    target.chmod(0o750)

    atomic_write(target, b"new")

    assert target.stat().st_mode & 0o777 == 0o750
