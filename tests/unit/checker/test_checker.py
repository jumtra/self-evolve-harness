import json
from pathlib import Path

from seh.artifacts import ArtifactStore
from seh.contracts import VerdictStatus
from seh.evals.checker import run_checks
from seh.evals.fixtures import EvalCase, TaskSpec, load_case, materialize


async def test_command_check_passes_on_expected_exit_code(tmp_path: Path):
    case_dir = tmp_path / "E42"
    (case_dir / "repo").mkdir(parents=True)
    (case_dir / "repo" / "a.txt").write_text("a\n")
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
                "checks": [
                    {
                        "id": "ok",
                        "type": "command",
                        "cmd": ["true"],
                        "cwd": "repo",
                        "expect_exit": 0,
                    }
                ],
                "write_allowlist": [],
                "expected_verdict_for_noop": "FAIL",
            }
        )
    )
    case = load_case(case_dir)
    work = materialize(case, tmp_path / "work")

    verdict, results = await run_checks(case, work)

    assert verdict.status is VerdictStatus.PASS
    assert verdict.node_id == "E42"
    assert (verdict.attempt, verdict.max_attempts) == (1, 1)
    assert [(r.check_id, r.passed) for r in results] == [("ok", True), ("write_allowlist", True)]


async def test_command_check_fails_on_unexpected_exit_code(tmp_path: Path):
    case_dir = tmp_path / "E42"
    (case_dir / "repo").mkdir(parents=True)
    (case_dir / "repo" / "a.txt").write_text("a\n")
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
                "checks": [
                    {
                        "id": "bad",
                        "type": "command",
                        "cmd": ["false"],
                        "cwd": "repo",
                        "expect_exit": 0,
                    }
                ],
                "write_allowlist": [],
                "expected_verdict_for_noop": "FAIL",
            }
        )
    )
    case = load_case(case_dir)
    work = materialize(case, tmp_path / "work")

    verdict, results = await run_checks(case, work)

    assert verdict.status is VerdictStatus.FAIL
    assert verdict.check_id == "bad"
    assert verdict.reason_code == "EXIT_CODE_MISMATCH"
    assert results[0].passed is False


async def test_command_check_fails_when_output_regex_missing(tmp_path: Path):
    case_dir = tmp_path / "E42"
    (case_dir / "repo").mkdir(parents=True)
    (case_dir / "repo" / "a.txt").write_text("a\n")
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
                "checks": [
                    {
                        "id": "out",
                        "type": "command",
                        "cmd": ["echo", "hello"],
                        "cwd": "repo",
                        "expect_exit": 0,
                        "output_regex": "goodbye",
                    }
                ],
                "write_allowlist": [],
                "expected_verdict_for_noop": "FAIL",
            }
        )
    )
    case = load_case(case_dir)
    work = materialize(case, tmp_path / "work")

    verdict, _ = await run_checks(case, work)

    assert verdict.status is VerdictStatus.FAIL
    assert verdict.reason_code == "OUTPUT_MISMATCH"


async def test_command_check_fails_on_timeout(tmp_path: Path):
    case_dir = tmp_path / "E42"
    (case_dir / "repo").mkdir(parents=True)
    (case_dir / "repo" / "a.txt").write_text("a\n")
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
                "checks": [
                    {
                        "id": "slow",
                        "type": "command",
                        "cmd": ["sleep", "30"],
                        "cwd": "repo",
                        "expect_exit": 0,
                    }
                ],
                "write_allowlist": [],
                "expected_verdict_for_noop": "FAIL",
            }
        )
    )
    case = load_case(case_dir)
    work = materialize(case, tmp_path / "work")

    verdict, _ = await run_checks(case, work, timeout_seconds=0.5)

    assert verdict.status is VerdictStatus.FAIL
    assert verdict.reason_code == "TIMEOUT"


async def test_command_evidence_is_masked_and_stored(tmp_path: Path):
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
                "checks": [
                    {
                        "id": "show",
                        "type": "command",
                        "cmd": ["cat", "conf.txt"],
                        "cwd": "repo",
                        "expect_exit": 0,
                    }
                ],
                "write_allowlist": [],
                "expected_verdict_for_noop": "FAIL",
            }
        )
    )
    case = load_case(case_dir)
    work = materialize(case, tmp_path / "work")
    store = ArtifactStore(tmp_path / "artifacts")

    verdict, results = await run_checks(case, work, artifacts=store)

    secret = "sk-ant-" + "a" * 40
    assert (work / "conf.txt").read_text() == f"token={secret}\n"
    assert verdict.evidence
    stored = store.resolve(results[0].evidence[0].uri).read_text()
    assert "token=" in stored
    assert secret not in stored


async def test_diff_scope_passes_for_change_inside_allow(tmp_path: Path):
    case_dir = tmp_path / "E42"
    (case_dir / "repo").mkdir(parents=True)
    (case_dir / "repo" / "a.py").write_text("x = 1\n")
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
                "checks": [
                    {
                        "id": "ok",
                        "type": "command",
                        "cmd": ["true"],
                        "cwd": "repo",
                        "expect_exit": 0,
                    },
                    {"id": "scope", "type": "diff_scope", "allow": ["a.py"]},
                ],
                "write_allowlist": ["a.py"],
                "expected_verdict_for_noop": "FAIL",
            }
        )
    )
    case = load_case(case_dir)
    work = materialize(case, tmp_path / "work")
    (work / "a.py").write_text("x = 2\n")

    verdict, _ = await run_checks(case, work)

    assert verdict.status is VerdictStatus.PASS
    assert verdict.allowed_repair_scope == ("a.py",)


async def test_diff_scope_fails_for_modified_file_outside_allow(tmp_path: Path):
    case_dir = tmp_path / "E42"
    (case_dir / "repo").mkdir(parents=True)
    (case_dir / "repo" / "a.py").write_text("x = 1\n")
    (case_dir / "repo" / "b.py").write_text("y = 1\n")
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
                "checks": [
                    {
                        "id": "ok",
                        "type": "command",
                        "cmd": ["true"],
                        "cwd": "repo",
                        "expect_exit": 0,
                    },
                    {"id": "scope", "type": "diff_scope", "allow": ["a.py"]},
                ],
                "write_allowlist": ["a.py"],
                "expected_verdict_for_noop": "FAIL",
            }
        )
    )
    case = load_case(case_dir)
    work = materialize(case, tmp_path / "work")
    (work / "b.py").write_text("y = 2\n")

    verdict, _ = await run_checks(case, work)

    assert verdict.status is VerdictStatus.FAIL
    assert verdict.check_id == "scope"
    assert verdict.reason_code == "OUT_OF_SCOPE_CHANGE"


async def test_diff_scope_detects_untracked_file_outside_allow(tmp_path: Path):
    case_dir = tmp_path / "E42"
    (case_dir / "repo").mkdir(parents=True)
    (case_dir / "repo" / "a.py").write_text("x = 1\n")
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
                "checks": [
                    {
                        "id": "ok",
                        "type": "command",
                        "cmd": ["true"],
                        "cwd": "repo",
                        "expect_exit": 0,
                    },
                    {"id": "scope", "type": "diff_scope", "allow": ["a.py"]},
                ],
                "write_allowlist": ["a.py"],
                "expected_verdict_for_noop": "FAIL",
            }
        )
    )
    case = load_case(case_dir)
    work = materialize(case, tmp_path / "work")
    (work / "new_dir").mkdir()
    (work / "new_dir" / "extra.py").write_text("z = 1\n")

    verdict, results = await run_checks(case, work)

    assert verdict.status is VerdictStatus.FAIL
    assert "new_dir/extra.py" in results[1].detail


async def test_diff_scope_detects_deleted_file_outside_allow(tmp_path: Path):
    case_dir = tmp_path / "E42"
    (case_dir / "repo").mkdir(parents=True)
    (case_dir / "repo" / "a.py").write_text("x = 1\n")
    (case_dir / "repo" / "b.py").write_text("y = 1\n")
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
                "checks": [
                    {
                        "id": "ok",
                        "type": "command",
                        "cmd": ["true"],
                        "cwd": "repo",
                        "expect_exit": 0,
                    },
                    {"id": "scope", "type": "diff_scope", "allow": ["a.py"]},
                ],
                "write_allowlist": ["a.py"],
                "expected_verdict_for_noop": "FAIL",
            }
        )
    )
    case = load_case(case_dir)
    work = materialize(case, tmp_path / "work")
    (work / "b.py").unlink()

    verdict, _ = await run_checks(case, work)

    assert verdict.status is VerdictStatus.FAIL
    assert verdict.reason_code == "OUT_OF_SCOPE_CHANGE"


async def test_diff_scope_ignores_bytecode_and_pytest_cache(tmp_path: Path):
    case_dir = tmp_path / "E42"
    (case_dir / "repo").mkdir(parents=True)
    (case_dir / "repo" / "a.py").write_text("x = 1\n")
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
                "checks": [
                    {
                        "id": "ok",
                        "type": "command",
                        "cmd": ["true"],
                        "cwd": "repo",
                        "expect_exit": 0,
                    },
                    {"id": "scope", "type": "diff_scope", "allow": ["a.py"]},
                ],
                "write_allowlist": ["a.py"],
                "expected_verdict_for_noop": "FAIL",
            }
        )
    )
    case = load_case(case_dir)
    work = materialize(case, tmp_path / "work")
    (work / "__pycache__").mkdir()
    (work / "__pycache__" / "a.cpython-311.pyc").write_bytes(b"\0")
    (work / ".pytest_cache").mkdir()
    (work / ".pytest_cache" / "v").write_text("1")

    verdict, _ = await run_checks(case, work)

    assert verdict.status is VerdictStatus.PASS


async def test_file_contains_passes_when_regex_matches(tmp_path: Path):
    case_dir = tmp_path / "E42"
    (case_dir / "repo").mkdir(parents=True)
    (case_dir / "repo" / "a.txt").write_text("version = 2\n")
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
                "checks": [
                    {
                        "id": "has",
                        "type": "file_contains",
                        "path": "a.txt",
                        "regex": "version = \\d",
                    }
                ],
                "write_allowlist": [],
                "expected_verdict_for_noop": "PASS",
            }
        )
    )
    case = load_case(case_dir)
    work = materialize(case, tmp_path / "work")

    verdict, _ = await run_checks(case, work)

    assert verdict.status is VerdictStatus.PASS


async def test_file_contains_fails_when_regex_missing(tmp_path: Path):
    case_dir = tmp_path / "E42"
    (case_dir / "repo").mkdir(parents=True)
    (case_dir / "repo" / "a.txt").write_text("version = 2\n")
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
                "checks": [{"id": "has", "type": "file_contains", "path": "a.txt", "regex": "zzz"}],
                "write_allowlist": [],
                "expected_verdict_for_noop": "FAIL",
            }
        )
    )
    case = load_case(case_dir)
    work = materialize(case, tmp_path / "work")

    verdict, _ = await run_checks(case, work)

    assert verdict.status is VerdictStatus.FAIL
    assert verdict.reason_code == "PATTERN_NOT_FOUND"


async def test_file_contains_present_false_fails_when_pattern_exists(tmp_path: Path):
    case_dir = tmp_path / "E42"
    (case_dir / "repo").mkdir(parents=True)
    (case_dir / "repo" / "a.txt").write_text("TODO\n")
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
                "checks": [
                    {
                        "id": "no_todo",
                        "type": "file_contains",
                        "path": "a.txt",
                        "regex": "TODO",
                        "present": False,
                    }
                ],
                "write_allowlist": [],
                "expected_verdict_for_noop": "FAIL",
            }
        )
    )
    case = load_case(case_dir)
    work = materialize(case, tmp_path / "work")

    verdict, _ = await run_checks(case, work)

    assert verdict.status is VerdictStatus.FAIL
    assert verdict.reason_code == "PATTERN_PRESENT"


async def test_file_contains_missing_file_fails(tmp_path: Path):
    case_dir = tmp_path / "E42"
    (case_dir / "repo").mkdir(parents=True)
    (case_dir / "repo" / "a.txt").write_text("x\n")
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
                "checks": [
                    {"id": "has", "type": "file_contains", "path": "nope.txt", "regex": "x"}
                ],
                "write_allowlist": [],
                "expected_verdict_for_noop": "FAIL",
            }
        )
    )
    case = load_case(case_dir)
    work = materialize(case, tmp_path / "work")

    verdict, _ = await run_checks(case, work)

    assert verdict.status is VerdictStatus.FAIL
    assert verdict.reason_code == "FILE_NOT_FOUND"


async def test_json_schema_passes_for_conforming_document(tmp_path: Path):
    case_dir = tmp_path / "E42"
    (case_dir / "repo").mkdir(parents=True)
    (case_dir / "repo" / "out.json").write_text('{"n": 3}')
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
                "checks": [
                    {
                        "id": "shape",
                        "type": "json_schema",
                        "path": "out.json",
                        "schema": {
                            "type": "object",
                            "required": ["n"],
                            "properties": {"n": {"type": "integer"}},
                        },
                    }
                ],
                "write_allowlist": [],
                "expected_verdict_for_noop": "PASS",
            }
        )
    )
    case = load_case(case_dir)
    work = materialize(case, tmp_path / "work")

    verdict, _ = await run_checks(case, work)

    assert verdict.status is VerdictStatus.PASS


async def test_json_schema_fails_for_violating_document(tmp_path: Path):
    case_dir = tmp_path / "E42"
    (case_dir / "repo").mkdir(parents=True)
    (case_dir / "repo" / "out.json").write_text('{"n": "three"}')
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
                "checks": [
                    {
                        "id": "shape",
                        "type": "json_schema",
                        "path": "out.json",
                        "schema": {"type": "object", "properties": {"n": {"type": "integer"}}},
                    }
                ],
                "write_allowlist": [],
                "expected_verdict_for_noop": "FAIL",
            }
        )
    )
    case = load_case(case_dir)
    work = materialize(case, tmp_path / "work")

    verdict, _ = await run_checks(case, work)

    assert verdict.status is VerdictStatus.FAIL
    assert verdict.reason_code == "SCHEMA_VIOLATION"


async def test_json_schema_fails_for_invalid_json(tmp_path: Path):
    case_dir = tmp_path / "E42"
    (case_dir / "repo").mkdir(parents=True)
    (case_dir / "repo" / "out.json").write_text("{broken")
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
                "checks": [
                    {"id": "shape", "type": "json_schema", "path": "out.json", "schema": {}}
                ],
                "write_allowlist": [],
                "expected_verdict_for_noop": "FAIL",
            }
        )
    )
    case = load_case(case_dir)
    work = materialize(case, tmp_path / "work")

    verdict, _ = await run_checks(case, work)

    assert verdict.status is VerdictStatus.FAIL
    assert verdict.reason_code == "INVALID_JSON"


async def test_forbidden_change_fails_when_protected_file_modified(tmp_path: Path):
    case_dir = tmp_path / "E42"
    (case_dir / "repo" / "tests").mkdir(parents=True)
    (case_dir / "repo" / "tests" / "t.py").write_text("assert True\n")
    (case_dir / "repo" / "a.py").write_text("x = 1\n")
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
                "checks": [
                    {
                        "id": "ok",
                        "type": "command",
                        "cmd": ["true"],
                        "cwd": "repo",
                        "expect_exit": 0,
                    },
                    {"id": "frozen", "type": "forbidden_change", "paths": ["tests/**"]},
                ],
                "write_allowlist": ["a.py", "tests/**"],
                "expected_verdict_for_noop": "FAIL",
            }
        )
    )
    case = load_case(case_dir)
    work = materialize(case, tmp_path / "work")
    (work / "tests" / "t.py").write_text("assert False\n")

    verdict, _ = await run_checks(case, work)

    assert verdict.status is VerdictStatus.FAIL
    assert verdict.check_id == "frozen"
    assert verdict.reason_code == "FORBIDDEN_CHANGE"


async def test_forbidden_change_fails_when_protected_file_deleted(tmp_path: Path):
    case_dir = tmp_path / "E42"
    (case_dir / "repo" / "tests").mkdir(parents=True)
    (case_dir / "repo" / "tests" / "t.py").write_text("assert True\n")
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
                "checks": [
                    {
                        "id": "ok",
                        "type": "command",
                        "cmd": ["true"],
                        "cwd": "repo",
                        "expect_exit": 0,
                    },
                    {"id": "frozen", "type": "forbidden_change", "paths": ["tests/**"]},
                ],
                "write_allowlist": ["tests/**"],
                "expected_verdict_for_noop": "FAIL",
            }
        )
    )
    case = load_case(case_dir)
    work = materialize(case, tmp_path / "work")
    (work / "tests" / "t.py").unlink()

    verdict, _ = await run_checks(case, work)

    assert verdict.reason_code == "FORBIDDEN_CHANGE"


async def test_forbidden_change_passes_when_protected_files_untouched(tmp_path: Path):
    case_dir = tmp_path / "E42"
    (case_dir / "repo" / "tests").mkdir(parents=True)
    (case_dir / "repo" / "tests" / "t.py").write_text("assert True\n")
    (case_dir / "repo" / "a.py").write_text("x = 1\n")
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
                "checks": [
                    {
                        "id": "ok",
                        "type": "command",
                        "cmd": ["true"],
                        "cwd": "repo",
                        "expect_exit": 0,
                    },
                    {"id": "frozen", "type": "forbidden_change", "paths": ["tests/**"]},
                ],
                "write_allowlist": ["a.py"],
                "expected_verdict_for_noop": "FAIL",
            }
        )
    )
    case = load_case(case_dir)
    work = materialize(case, tmp_path / "work")
    (work / "a.py").write_text("x = 2\n")

    verdict, _ = await run_checks(case, work)

    assert verdict.status is VerdictStatus.PASS


async def test_write_allowlist_is_enforced_even_without_diff_scope_check(tmp_path: Path):
    case_dir = tmp_path / "E42"
    (case_dir / "repo").mkdir(parents=True)
    (case_dir / "repo" / "a.py").write_text("x = 1\n")
    (case_dir / "repo" / "b.py").write_text("y = 1\n")
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
                "checks": [
                    {
                        "id": "ok",
                        "type": "command",
                        "cmd": ["true"],
                        "cwd": "repo",
                        "expect_exit": 0,
                    }
                ],
                "write_allowlist": ["a.py"],
                "expected_verdict_for_noop": "FAIL",
            }
        )
    )
    case = load_case(case_dir)
    work = materialize(case, tmp_path / "work")
    (work / "b.py").write_text("y = 2\n")

    verdict, _ = await run_checks(case, work)

    assert verdict.status is VerdictStatus.FAIL
    assert verdict.check_id == "write_allowlist"


async def test_unknown_check_type_fails_with_unknown_check(tmp_path: Path):
    case_dir = tmp_path / "E42"
    (case_dir / "repo").mkdir(parents=True)
    (case_dir / "repo" / "a.py").write_text("x = 1\n")
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
                "checks": [
                    {
                        "id": "ok",
                        "type": "command",
                        "cmd": ["true"],
                        "cwd": "repo",
                        "expect_exit": 0,
                    },
                    {"id": "weird", "type": "vibes_check"},
                ],
                "write_allowlist": [],
                "expected_verdict_for_noop": "FAIL",
            }
        )
    )
    case = load_case(case_dir)
    work = materialize(case, tmp_path / "work")

    verdict, _ = await run_checks(case, work)

    assert verdict.status is VerdictStatus.FAIL
    assert verdict.check_id == "weird"
    assert verdict.reason_code == "UNKNOWN_CHECK"


async def test_check_exception_becomes_checker_error_not_pass(tmp_path: Path):
    case_dir = tmp_path / "E42"
    (case_dir / "repo").mkdir(parents=True)
    (case_dir / "repo" / "a.py").write_text("x = 1\n")
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
                "checks": [
                    {
                        "id": "ok",
                        "type": "command",
                        "cmd": ["true"],
                        "cwd": "repo",
                        "expect_exit": 0,
                    },
                    {"id": "badre", "type": "file_contains", "path": "a.py", "regex": "(unclosed"},
                    {"id": "nocmd", "type": "command", "cwd": "repo", "expect_exit": 0},
                ],
                "write_allowlist": [],
                "expected_verdict_for_noop": "FAIL",
            }
        )
    )
    case = load_case(case_dir)
    work = materialize(case, tmp_path / "work")

    verdict, results = await run_checks(case, work)

    assert verdict.status is VerdictStatus.FAIL
    assert [r.reason_code for r in results if r.check_id in ("badre", "nocmd")] == [
        "CHECKER_ERROR",
        "CHECKER_ERROR",
    ]


async def test_command_cwd_escaping_workdir_is_checker_error(tmp_path: Path):
    case_dir = tmp_path / "E42"
    (case_dir / "repo").mkdir(parents=True)
    (case_dir / "repo" / "a.py").write_text("x = 1\n")
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
                "checks": [
                    {
                        "id": "esc",
                        "type": "command",
                        "cmd": ["true"],
                        "cwd": "../..",
                        "expect_exit": 0,
                    }
                ],
                "write_allowlist": [],
                "expected_verdict_for_noop": "FAIL",
            }
        )
    )
    case = load_case(case_dir)
    work = materialize(case, tmp_path / "work")

    verdict, results = await run_checks(case, work)

    assert verdict.status is VerdictStatus.FAIL
    assert results[0].reason_code == "CHECKER_ERROR"


async def test_empty_checks_fail_with_no_positive_evidence(tmp_path: Path):
    (tmp_path / "repo").mkdir()
    (tmp_path / "repo" / "a.py").write_text("x = 1\n")
    case = EvalCase(
        schema_version=1,
        id="E42",
        title="t",
        split="training",
        kind="bugfix",
        task=TaskSpec(goal="g", acceptance=()),
        repo_dir=tmp_path / "repo",
        expand_suffix=False,
        checks=(),
        write_allowlist=(),
        expected_verdict_for_noop=VerdictStatus.FAIL,
        secrets={},
    )
    work = materialize(case, tmp_path / "work")

    verdict, _ = await run_checks(case, work)

    assert verdict.status is VerdictStatus.FAIL
    assert verdict.reason_code == "NO_POSITIVE_EVIDENCE"


async def test_only_negative_checks_fail_with_no_positive_evidence(tmp_path: Path):
    case_dir = tmp_path / "E42"
    (case_dir / "repo").mkdir(parents=True)
    (case_dir / "repo" / "a.py").write_text("x = 1\n")
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
                "checks": [
                    {"id": "scope", "type": "diff_scope", "allow": ["a.py"]},
                    {"id": "frozen", "type": "forbidden_change", "paths": ["b.py"]},
                    {
                        "id": "no_todo",
                        "type": "file_contains",
                        "path": "a.py",
                        "regex": "TODO",
                        "present": False,
                    },
                ],
                "write_allowlist": ["a.py"],
                "expected_verdict_for_noop": "FAIL",
            }
        )
    )
    case = load_case(case_dir)
    work = materialize(case, tmp_path / "work")

    verdict, results = await run_checks(case, work)

    assert all(r.passed for r in results)
    assert verdict.status is VerdictStatus.FAIL
    assert verdict.reason_code == "NO_POSITIVE_EVIDENCE"


async def test_agent_written_self_assessment_is_not_evidence(tmp_path: Path):
    case_dir = tmp_path / "E42"
    (case_dir / "repo").mkdir(parents=True)
    (case_dir / "repo" / "a.py").write_text("x = 1\n")
    (case_dir / "case.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "id": "E42",
                "title": "t",
                "split": "holdout",
                "kind": "self_eval",
                "task": {"goal": "g", "acceptance": []},
                "repo": "repo/",
                "checks": [
                    {
                        "id": "fails",
                        "type": "command",
                        "cmd": ["false"],
                        "cwd": "repo",
                        "expect_exit": 0,
                    }
                ],
                "write_allowlist": ["*.md"],
                "expected_verdict_for_noop": "FAIL",
            }
        )
    )
    case = load_case(case_dir)
    work = materialize(case, tmp_path / "work")
    (work / "DONE.md").write_text("verdict: PASS. all checks complete\n")

    verdict, _ = await run_checks(case, work)

    assert verdict.status is VerdictStatus.FAIL
    assert verdict.check_id == "fails"
