import json
import subprocess
from pathlib import Path

import pytest

from seh.evals.fixtures import FixtureError, load_case, load_suite, materialize


def test_load_case_parses_all_fields(tmp_path: Path):
    case_dir = tmp_path / "E42"
    (case_dir / "repo").mkdir(parents=True)
    (case_dir / "case.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "id": "E42",
                "title": "t",
                "split": "holdout",
                "kind": "bugfix",
                "task": {"goal": "g", "acceptance": ["a1"]},
                "repo": "repo/",
                "expand_suffix": True,
                "checks": [{"id": "c1", "type": "diff_scope", "allow": ["x.py"]}],
                "write_allowlist": ["x.py"],
                "expected_verdict_for_noop": "FAIL",
            }
        )
    )

    case = load_case(case_dir / "case.json")

    assert case.id == "E42"
    assert case.split == "holdout"
    assert case.task.goal == "g"
    assert case.task.acceptance == ("a1",)
    assert case.repo_dir == case_dir / "repo"
    assert case.expand_suffix is True
    assert case.checks[0].id == "c1"
    assert case.checks[0].type == "diff_scope"
    assert case.checks[0].params == {"allow": ["x.py"]}
    assert case.write_allowlist == ("x.py",)


def test_load_case_rejects_id_not_matching_directory(tmp_path: Path):
    case_dir = tmp_path / "E01"
    case_dir.mkdir()
    (case_dir / "case.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "id": "E02",
                "title": "t",
                "split": "training",
                "kind": "bugfix",
                "task": {"goal": "g", "acceptance": []},
                "repo": "repo/",
                "checks": [{"id": "c", "type": "diff_scope", "allow": []}],
                "write_allowlist": [],
                "expected_verdict_for_noop": "FAIL",
            }
        )
    )

    with pytest.raises(FixtureError):
        load_case(case_dir / "case.json")


def test_load_case_rejects_empty_checks(tmp_path: Path):
    case_dir = tmp_path / "E01"
    case_dir.mkdir()
    (case_dir / "case.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "id": "E01",
                "title": "t",
                "split": "training",
                "kind": "bugfix",
                "task": {"goal": "g", "acceptance": []},
                "repo": "repo/",
                "checks": [],
                "write_allowlist": [],
                "expected_verdict_for_noop": "FAIL",
            }
        )
    )

    with pytest.raises(FixtureError):
        load_case(case_dir / "case.json")


def test_load_case_rejects_duplicate_check_ids(tmp_path: Path):
    case_dir = tmp_path / "E01"
    case_dir.mkdir()
    (case_dir / "case.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "id": "E01",
                "title": "t",
                "split": "training",
                "kind": "bugfix",
                "task": {"goal": "g", "acceptance": []},
                "repo": "repo/",
                "checks": [
                    {"id": "c", "type": "diff_scope", "allow": []},
                    {"id": "c", "type": "diff_scope", "allow": []},
                ],
                "write_allowlist": [],
                "expected_verdict_for_noop": "FAIL",
            }
        )
    )

    with pytest.raises(FixtureError):
        load_case(case_dir / "case.json")


def test_load_case_rejects_malformed_json(tmp_path: Path):
    case_dir = tmp_path / "E01"
    case_dir.mkdir()
    (case_dir / "case.json").write_text("{not json")

    with pytest.raises(FixtureError):
        load_case(case_dir / "case.json")


def test_load_suite_loads_every_case_in_id_order():
    cases = load_suite()

    assert [c.id for c in cases] == [f"E{i:02d}" for i in range(1, 11)]


def test_materialize_copies_repo_and_creates_baseline_commit(tmp_path: Path):
    case_dir = tmp_path / "E42"
    (case_dir / "repo" / "sub").mkdir(parents=True)
    (case_dir / "repo" / "sub" / "a.py").write_text("x = 1\n")
    (case_dir / "case.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "id": "E42",
                "title": "t",
                "split": "training",
                "kind": "bugfix",
                "task": {"goal": "g", "acceptance": []},
                "repo": "repo/",
                "checks": [{"id": "c", "type": "diff_scope", "allow": []}],
                "write_allowlist": [],
                "expected_verdict_for_noop": "FAIL",
            }
        )
    )
    case = load_case(case_dir)

    work = materialize(case, tmp_path / "work")

    assert (work / "sub" / "a.py").read_text() == "x = 1\n"
    status = subprocess.run(
        ["git", "status", "--porcelain"], cwd=work, capture_output=True, text=True, check=True
    )
    assert status.stdout == ""
    tracked = subprocess.run(
        ["git", "ls-files"], cwd=work, capture_output=True, text=True, check=True
    )
    assert tracked.stdout.split() == ["sub/a.py"]


def test_materialize_keeps_fixture_suffix_when_expand_suffix_false(tmp_path: Path):
    case_dir = tmp_path / "E42"
    (case_dir / "repo").mkdir(parents=True)
    (case_dir / "repo" / "CLAUDE.md.fixture").write_text("data\n")
    (case_dir / "case.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "id": "E42",
                "title": "t",
                "split": "training",
                "kind": "bugfix",
                "task": {"goal": "g", "acceptance": []},
                "repo": "repo/",
                "expand_suffix": False,
                "checks": [{"id": "c", "type": "diff_scope", "allow": []}],
                "write_allowlist": [],
                "expected_verdict_for_noop": "FAIL",
            }
        )
    )

    work = materialize(load_case(case_dir), tmp_path / "work")

    assert (work / "CLAUDE.md.fixture").exists()
    assert not (work / "CLAUDE.md").exists()


def test_materialize_strips_fixture_suffix_when_expand_suffix_true(tmp_path: Path):
    case_dir = tmp_path / "E42"
    (case_dir / "repo" / "d").mkdir(parents=True)
    (case_dir / "repo" / "d" / "SKILL.md.fixture").write_text("data\n")
    (case_dir / "case.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "id": "E42",
                "title": "t",
                "split": "training",
                "kind": "bugfix",
                "task": {"goal": "g", "acceptance": []},
                "repo": "repo/",
                "expand_suffix": True,
                "checks": [{"id": "c", "type": "diff_scope", "allow": []}],
                "write_allowlist": [],
                "expected_verdict_for_noop": "FAIL",
            }
        )
    )

    work = materialize(load_case(case_dir), tmp_path / "work")

    assert (work / "d" / "SKILL.md").read_text() == "data\n"
    assert not (work / "d" / "SKILL.md.fixture").exists()


def test_materialize_generates_secret_template_value_into_files(tmp_path: Path):
    case_dir = tmp_path / "E42"
    (case_dir / "repo").mkdir(parents=True)
    (case_dir / "repo" / "conf.txt").write_text("token={TOKEN}\n")
    (case_dir / "case.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "id": "E42",
                "title": "t",
                "split": "training",
                "kind": "bugfix",
                "task": {"goal": "g", "acceptance": []},
                "repo": "repo/",
                "secrets": {
                    "TOKEN": {"secret_template": {"prefix": "sk-ant-", "fill": "a", "length": 40}}
                },
                "checks": [{"id": "c", "type": "diff_scope", "allow": []}],
                "write_allowlist": [],
                "expected_verdict_for_noop": "FAIL",
            }
        )
    )

    work = materialize(load_case(case_dir), tmp_path / "work")

    expected = "sk-ant-" + "a" * 40
    assert (work / "conf.txt").read_text() == f"token={expected}\n"


def test_materialize_supports_parts_secret_template(tmp_path: Path):
    case_dir = tmp_path / "E42"
    (case_dir / "repo").mkdir(parents=True)
    (case_dir / "repo" / "k.txt").write_text("{PEM}")
    (case_dir / "case.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "id": "E42",
                "title": "t",
                "split": "training",
                "kind": "bugfix",
                "task": {"goal": "g", "acceptance": []},
                "repo": "repo/",
                "secrets": {"PEM": {"secret_template": {"parts": ["-----BEGIN ", "X", " Y-----"]}}},
                "checks": [{"id": "c", "type": "diff_scope", "allow": []}],
                "write_allowlist": [],
                "expected_verdict_for_noop": "FAIL",
            }
        )
    )

    work = materialize(load_case(case_dir), tmp_path / "work")

    assert (work / "k.txt").read_text() == "-----BEGIN " + "X" + " Y-----"


def test_materialize_refuses_non_empty_destination(tmp_path: Path):
    case_dir = tmp_path / "E42"
    (case_dir / "repo").mkdir(parents=True)
    (case_dir / "case.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "id": "E42",
                "title": "t",
                "split": "training",
                "kind": "bugfix",
                "task": {"goal": "g", "acceptance": []},
                "repo": "repo/",
                "checks": [{"id": "c", "type": "diff_scope", "allow": []}],
                "write_allowlist": [],
                "expected_verdict_for_noop": "FAIL",
            }
        )
    )
    (tmp_path / "work").mkdir()
    (tmp_path / "work" / "stale.txt").write_text("x")

    with pytest.raises(FixtureError):
        materialize(load_case(case_dir), tmp_path / "work")
