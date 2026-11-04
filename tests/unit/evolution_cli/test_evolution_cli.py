import json
from pathlib import Path

import pytest

from seh.commands.evolve import _read_changes, _validate_id


def test_candidate_id_cannot_escape() -> None:
    for value in ("../x", ".", "a/b", "-x"):
        with pytest.raises(ValueError):
            _validate_id(value)


def test_change_file_requires_nonempty_string_values(tmp_path: Path) -> None:
    source = tmp_path / "changes.json"
    source.write_text(json.dumps({"file.txt": "new"}))
    assert _read_changes(source) == {"file.txt": "new"}
    source.write_text('{"file.txt": 42}')
    with pytest.raises(ValueError):
        _read_changes(source)


def test_authoring_change_requires_record(tmp_path: Path) -> None:
    from seh.evolution.authoring_guard import check_authoring_gate

    with pytest.raises(ValueError, match="AUTHORING_RECORD_REQUIRED"):
        check_authoring_gate(tmp_path, {".harness/spec/skills/a.yaml": b"new"}, None)


def test_propose_cli_creates_isolated_candidate(tmp_path: Path) -> None:
    import subprocess

    from seh.cli import main
    from seh.commands.evolve import _load, _snapshots

    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / "file.txt").write_text("old")
    subprocess.run(["git", "-C", str(tmp_path), "add", "file.txt"], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(tmp_path),
            "-c",
            "user.name=t",
            "-c",
            "user.email=t@x",
            "commit",
            "-qm",
            "base",
        ],
        check=True,
    )
    attempts = tmp_path / ".harness/state/runs/run1/attempts"
    attempts.mkdir(parents=True)
    (attempts / "worker.jsonl").write_text(
        '{"attempt":1,"verdict_status":"FAIL","reason_code":"CHECK_FAILED"}\n'
    )
    changes = tmp_path.parent / f"{tmp_path.name}-changes.json"
    changes.write_text('{"file.txt": "new"}')
    assert (
        main(
            [
                "evolve",
                "propose",
                "--root",
                str(tmp_path),
                "--from",
                "run1",
                "--id",
                "c1",
                "--changes",
                str(changes),
            ]
        )
        == 0
    )
    before, after = _snapshots(tmp_path, _load(tmp_path, "c1"))
    assert before == {"file.txt": b"old"}
    assert after == {"file.txt": b"new"}
    assert (tmp_path / "file.txt").read_text() == "old"


def test_propose_rejects_missing_source_evidence(tmp_path: Path) -> None:
    import argparse

    from seh.commands.evolve import _propose

    changes = tmp_path / "changes.json"
    changes.write_text('{"file.txt": "new"}')
    args = argparse.Namespace(
        root=str(tmp_path), id="candidate", source="missing", changes=str(changes)
    )
    with pytest.raises(ValueError, match="SOURCE_EVIDENCE"):
        _propose(args)
