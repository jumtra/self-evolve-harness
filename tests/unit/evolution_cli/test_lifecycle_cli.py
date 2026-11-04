import json
from datetime import UTC, datetime, timedelta

from seh.cli import main


def test_retire_persists_only_old_generated_candidates(tmp_path):
    directory = tmp_path / ".harness/state/evolution"
    directory.mkdir(parents=True)
    now = datetime.now(UTC)
    for name, generated, age in [("old", True, 40), ("user", False, 40), ("new", True, 1)]:
        (directory / f"{name}.json").write_text(
            json.dumps(
                {
                    "candidate_id": name,
                    "status": "proposed",
                    "generated": generated,
                    "updated_at": (now - timedelta(days=age)).isoformat(),
                }
            )
        )
    assert main(["evolve", "retire", "--root", str(tmp_path), "--days", "30"]) == 0
    assert json.loads((directory / "old.json").read_text())["status"] == "retired"
    assert json.loads((directory / "user.json").read_text())["status"] == "proposed"
    assert json.loads((directory / "new.json").read_text())["status"] == "proposed"


def test_learning_cli_requires_matching_promoted_evidence(tmp_path):
    from seh.knowledge import constraints_for

    directory = tmp_path / ".harness/evolution/promotions"
    directory.mkdir(parents=True)
    (directory / "p1.json").write_text(
        json.dumps({"snapshot_id": "p1", "evidence_refs": ["eval:1"]})
    )
    args = [
        "evolve",
        "learn",
        "--root",
        str(tmp_path),
        "--promotion",
        "p1",
        "--id",
        "c1",
        "--statement",
        "Keep tests",
        "--scope",
        "src/**",
        "--evidence",
        "eval:1",
    ]
    assert main(args) == 0
    assert constraints_for(tmp_path, ["src/a.py"], now=datetime.now(UTC))[0].id == "c1"
    args[-1] = "eval:other"
    assert main(args) == 1


def test_retired_candidate_cannot_be_benchmarked_or_promoted(tmp_path, capsys):
    directory = tmp_path / ".harness/state/evolution"
    directory.mkdir(parents=True)
    (directory / "old.json").write_text(json.dumps({"candidate_id": "old", "status": "retired"}))
    assert main(["evolve", "benchmark", "old", "--root", str(tmp_path)]) == 1
    assert "CANDIDATE_RETIRED" in capsys.readouterr().err
    assert main(["evolve", "promote", "old", "--root", str(tmp_path)]) == 1
    assert "CANDIDATE_RETIRED" in capsys.readouterr().err
