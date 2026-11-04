import pytest

from seh.contracts import SchemaError, load_schema, validate


def test_load_schema_task_spec_declares_draft_2020_12():
    schema = load_schema("task_spec")

    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"


def test_load_schema_unknown_name_raises_schema_error():
    with pytest.raises(SchemaError):
        load_schema("no_such_schema")


def test_validate_task_spec_valid_example_passes():
    data = {
        "id": "task-001",
        "goal": "期限切れトークンを拒否する",
        "acceptance": ["test_auth_expired exits 0"],
        "risk": "R0",
        "mode": "managed",
        "limits": {"max_parallel": 3, "max_attempts_per_unit": 3, "max_wall_seconds": 1800},
        "required_capabilities": ["git.diff"],
    }

    validate("task_spec", data)


@pytest.mark.parametrize(
    "data",
    [
        pytest.param(
            {"id": "t", "acceptance": [], "risk": "R0", "mode": "native"},
            id="missing_goal",
        ),
        pytest.param(
            {"id": "t", "goal": "g", "acceptance": [], "risk": "contained", "mode": "native"},
            id="risk_not_in_enum",
        ),
        pytest.param(
            {"id": "t", "goal": "g", "acceptance": [], "risk": "R0", "mode": "native", "x": 1},
            id="extra_property",
        ),
    ],
)
def test_validate_task_spec_invalid_raises_schema_error(data):
    with pytest.raises(SchemaError):
        validate("task_spec", data)


def test_validate_work_unit_valid_example_passes():
    data = {
        "node_id": "worker-auth",
        "kind": "worker",
        "depends_on": ["split-001"],
        "inputs": {"spec_ref": "artifact://task-001/spec"},
        "outputs_schema": "schemas/work-unit-result.v1.json",
        "write_allowlist": ["src/auth/**"],
        "checks": ["tests.auth"],
        "risk": "R0",
    }

    validate("work_unit", data)


@pytest.mark.parametrize(
    "data",
    [
        pytest.param(
            {
                "node_id": "w",
                "kind": "worker",
                "depends_on": [],
                "inputs": {},
                "outputs_schema": None,
                "write_allowlist": [],
                "risk": "R0",
            },
            id="missing_checks",
        ),
        pytest.param(
            {
                "node_id": "w",
                "kind": "reviewer",
                "depends_on": [],
                "inputs": {},
                "outputs_schema": None,
                "write_allowlist": [],
                "checks": [],
                "risk": "R0",
            },
            id="kind_not_in_enum",
        ),
        pytest.param(
            {
                "node_id": "w",
                "kind": "gate",
                "depends_on": [],
                "inputs": {},
                "outputs_schema": None,
                "write_allowlist": [],
                "checks": [],
                "risk": "R0",
                "extra": True,
            },
            id="extra_property",
        ),
    ],
)
def test_validate_work_unit_invalid_raises_schema_error(data):
    with pytest.raises(SchemaError):
        validate("work_unit", data)


def test_validate_edge_valid_example_passes():
    data = {"from_node": "a", "from_output": "diff", "to_node": "b", "to_input": "patch"}

    validate("edge", data)


@pytest.mark.parametrize(
    "data",
    [
        pytest.param({"from_node": "a", "from_output": "o", "to_node": "b"}, id="missing_to_input"),
        pytest.param(
            {"from_node": 1, "from_output": "o", "to_node": "b", "to_input": "i"},
            id="from_node_not_string",
        ),
        pytest.param(
            {"from_node": "a", "from_output": "o", "to_node": "b", "to_input": "i", "x": 1},
            id="extra_property",
        ),
    ],
)
def test_validate_edge_invalid_raises_schema_error(data):
    with pytest.raises(SchemaError):
        validate("edge", data)


def test_validate_verdict_valid_example_passes():
    data = {
        "node_id": "worker-auth",
        "status": "FAIL",
        "check_id": "tests.auth",
        "reason_code": "ASSERTION_FAILED",
        "evidence": [{"uri": "artifact://run-1/test-log", "sha256": "abc"}],
        "allowed_repair_scope": ["src/auth/**"],
        "attempt": 1,
        "max_attempts": 3,
    }

    validate("verdict", data)


@pytest.mark.parametrize(
    "data",
    [
        pytest.param(
            {
                "node_id": "w",
                "status": "FAIL",
                "check_id": "c",
                "reason_code": "r",
                "evidence": [],
                "allowed_repair_scope": [],
                "attempt": 1,
            },
            id="missing_max_attempts",
        ),
        pytest.param(
            {
                "node_id": "w",
                "status": "PASSED",
                "check_id": "c",
                "reason_code": "r",
                "evidence": [],
                "allowed_repair_scope": [],
                "attempt": 1,
                "max_attempts": 3,
            },
            id="status_not_in_enum",
        ),
        pytest.param(
            {
                "node_id": "w",
                "status": "PASS",
                "check_id": "c",
                "reason_code": "r",
                "evidence": [{"uri": "u", "sha256": "s", "x": 1}],
                "allowed_repair_scope": [],
                "attempt": 1,
                "max_attempts": 3,
            },
            id="extra_property_in_evidence",
        ),
    ],
)
def test_validate_verdict_invalid_raises_schema_error(data):
    with pytest.raises(SchemaError):
        validate("verdict", data)


def test_validate_run_result_valid_example_with_unknown_usage_passes():
    data = {
        "run_id": "run-1",
        "host": "claude",
        "terminal_state": "SUCCESS",
        "exit_code": 0,
        "final_response": "done",
        "event_log_digest": None,
        "evidence_refs": [],
        "usage": {"input_tokens": None, "output_tokens": 0, "cost_usd": None, "raw": None},
        "error_code": None,
    }

    validate("run_result", data)


@pytest.mark.parametrize(
    "data",
    [
        pytest.param(
            {
                "run_id": "r",
                "host": "codex",
                "terminal_state": "SUCCESS",
                "exit_code": 0,
                "final_response": None,
                "event_log_digest": None,
                "evidence_refs": [],
                "usage": None,
            },
            id="missing_error_code",
        ),
        pytest.param(
            {
                "run_id": "r",
                "host": "codex",
                "terminal_state": "DONE",
                "exit_code": 0,
                "final_response": None,
                "event_log_digest": None,
                "evidence_refs": [],
                "usage": None,
                "error_code": None,
            },
            id="terminal_state_not_in_enum",
        ),
        pytest.param(
            {
                "run_id": "r",
                "host": "codex",
                "terminal_state": "FAILED",
                "exit_code": 1,
                "final_response": None,
                "event_log_digest": None,
                "evidence_refs": [],
                "usage": None,
                "error_code": "E",
                "extra": 1,
            },
            id="extra_property",
        ),
    ],
)
def test_validate_run_result_invalid_raises_schema_error(data):
    with pytest.raises(SchemaError):
        validate("run_result", data)


def test_validate_final_output_valid_example_passes():
    data = {
        "task_id": "task-001",
        "status": "PASSED",
        "summary": "期限切れトークンの判定とテストを追加",
        "changed_files": ["src/auth/expiry.py"],
        "evidence_refs": ["artifact://run-1/test-log"],
        "remaining_risks": [],
        "requires_human_approval": True,
    }

    validate("final_output", data)


@pytest.mark.parametrize(
    "data",
    [
        pytest.param(
            {
                "task_id": "t",
                "status": "PASSED",
                "summary": "s",
                "changed_files": [],
                "evidence_refs": [],
                "remaining_risks": [],
            },
            id="missing_requires_human_approval",
        ),
        pytest.param(
            {
                "task_id": "t",
                "status": "RUNNING",
                "summary": "s",
                "changed_files": [],
                "evidence_refs": [],
                "remaining_risks": [],
                "requires_human_approval": False,
            },
            id="status_not_terminal",
        ),
        pytest.param(
            {
                "task_id": "t",
                "status": "PASSED",
                "summary": "s",
                "changed_files": [],
                "evidence_refs": [],
                "remaining_risks": [],
                "requires_human_approval": False,
                "extra": 1,
            },
            id="extra_property",
        ),
    ],
)
def test_validate_final_output_invalid_raises_schema_error(data):
    with pytest.raises(SchemaError):
        validate("final_output", data)


def test_validate_authoring_record_valid_example_passes():
    data = {
        "id": "AUTH-20261104-001",
        "target_kind": "skill",
        "target_paths": [".claude/skills/work/SKILL.md"],
        "risk": "behavioral",
        "exploration": {"reuse_decision": "modify_existing"},
        "spec": {"goal": "検証が起動する"},
        "plan_ref": "plans/AUTH-20261104-001.json",
        "approval_ref": None,
        "baseline_run_id": "eval:b",
        "candidate_run_id": "eval:c",
        "state": "AWAITING_EVAL",
    }

    validate("authoring_record", data)


@pytest.mark.parametrize(
    "data",
    [
        pytest.param(
            {
                "id": "A",
                "target_kind": "skill",
                "target_paths": [],
                "risk": "text_only",
                "exploration": {},
                "state": "CLASSIFIED",
            },
            id="missing_spec",
        ),
        pytest.param(
            {
                "id": "A",
                "target_kind": "skill",
                "target_paths": [],
                "risk": "low",
                "exploration": {},
                "spec": {},
                "state": "CLASSIFIED",
            },
            id="risk_not_in_enum",
        ),
        pytest.param(
            {
                "id": "A",
                "target_kind": "skill",
                "target_paths": [],
                "risk": "high_risk",
                "exploration": {},
                "spec": {},
                "state": "CLASSIFIED",
                "extra": 1,
            },
            id="extra_property",
        ),
    ],
)
def test_validate_authoring_record_invalid_raises_schema_error(data):
    with pytest.raises(SchemaError):
        validate("authoring_record", data)


def test_validate_module_manifest_valid_example_passes():
    data = {
        "id": "code-intelligence.codegraph",
        "api_version": "1",
        "version": "1.0.0",
        "provides": ["code.search"],
        "requires": ["exec.local"],
        "conflicts": ["code-intelligence.graphify"],
        "default_enabled": False,
        "permissions": ["read:repository"],
        "healthcheck": ["codegraph --version"],
    }

    validate("module_manifest", data)


@pytest.mark.parametrize(
    "data",
    [
        pytest.param(
            {"id": "m", "api_version": "1", "version": "1.0.0", "healthcheck": ["x"]},
            id="missing_provides",
        ),
        pytest.param(
            {"id": "m", "api_version": "1", "version": "1.0.0", "provides": []},
            id="missing_health_command",
        ),
        pytest.param(
            {
                "id": "m",
                "api_version": "1",
                "version": "1.0.0",
                "provides": [],
                "health_command": ["x"],
                "default_enabled": "yes",
            },
            id="default_enabled_not_boolean",
        ),
        pytest.param(
            {
                "id": "m",
                "api_version": "1",
                "version": "1.0.0",
                "provides": [],
                "health_command": ["x"],
                "extra": 1,
            },
            id="extra_property",
        ),
    ],
)
def test_validate_module_manifest_invalid_raises_schema_error(data):
    with pytest.raises(SchemaError):
        validate("module_manifest", data)
