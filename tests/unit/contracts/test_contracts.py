from datetime import UTC, datetime, timedelta

import pytest

from seh.contracts import (
    ApprovalToken,
    Evidence,
    ModuleManifest,
    Result,
    ResultStatus,
    TerminalState,
    Usage,
    Verdict,
    VerdictStatus,
)


def test_usage_none_tokens_differ_from_zero_tokens():
    unknown = Usage(input_tokens=None, output_tokens=None, cost_usd=None, raw=None)
    zero = Usage(input_tokens=0, output_tokens=0, cost_usd=0.0, raw=None)

    assert unknown != zero


def test_result_unsupported_differs_from_empty_ok():
    unsupported = Result(status=ResultStatus.UNSUPPORTED)
    empty_ok = Result(status=ResultStatus.OK, data=[])

    assert (unsupported.ok, empty_ok.ok) == (False, True)


def test_terminal_state_values_include_all_cli_runner_outcomes():
    names = {s.value for s in TerminalState}

    assert names == {
        "SUCCESS", "FAILED", "BLOCKED_AUTH", "POLICY_BLOCKED",
        "UNSUPPORTED", "INVALID_OUTPUT", "TIMED_OUT", "CANCELLED",
    }  # fmt: skip


def test_verdict_as_repair_input_lists_check_reason_evidence_uris_and_scope():
    verdict = Verdict(
        node_id="worker-auth",
        status=VerdictStatus.FAIL,
        check_id="tests.auth",
        reason_code="ASSERTION_FAILED",
        evidence=(Evidence(uri="artifact://run-1/test-log", sha256="abc"),),
        allowed_repair_scope=("src/auth/**",),
        attempt=1,
        max_attempts=3,
    )

    repair_input = verdict.as_repair_input()

    assert repair_input == {
        "failed_check": "tests.auth",
        "reason": "ASSERTION_FAILED",
        "evidence": ["artifact://run-1/test-log"],
        "allowed_scope": ["src/auth/**"],
    }


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (VerdictStatus.PASS, True),
        (VerdictStatus.FAIL, False),
        (VerdictStatus.BLOCKED, False),
    ],
)
def test_verdict_passed_is_true_only_for_pass(status, expected):
    verdict = Verdict("n", status, "c", "r", (), (), 1, 3)

    assert verdict.passed is expected


def test_approval_token_matching_scope_and_digest_before_expiry_is_valid():
    now = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)
    token = ApprovalToken(
        id="tok-1",
        scope=("src/auth/**",),
        target_digest="d1",
        expires_at=now + timedelta(minutes=5),
        issued_by="user",
    )

    valid = token.is_valid_for("src/auth/login.py", "d1", now)

    assert valid is True


def test_approval_token_expired_is_invalid():
    now = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)
    token = ApprovalToken(
        id="tok-1",
        scope=("src/auth/**",),
        target_digest="d1",
        expires_at=now - timedelta(seconds=1),
        issued_by="user",
    )

    valid = token.is_valid_for("src/auth/login.py", "d1", now)

    assert valid is False


def test_approval_token_digest_mismatch_is_invalid():
    now = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)
    token = ApprovalToken(
        id="tok-1",
        scope=("src/auth/**",),
        target_digest="d1",
        expires_at=now + timedelta(minutes=5),
        issued_by="user",
    )

    valid = token.is_valid_for("src/auth/login.py", "tampered", now)

    assert valid is False


def test_approval_token_scope_outside_is_invalid():
    now = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)
    token = ApprovalToken(
        id="tok-1",
        scope=("src/auth/**",),
        target_digest="d1",
        expires_at=now + timedelta(minutes=5),
        issued_by="user",
    )

    valid = token.is_valid_for("src/billing/pay.py", "d1", now)

    assert valid is False


def test_module_manifest_from_mapping_design_example_parses_with_defaults():
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

    manifest = ModuleManifest.from_mapping(data)

    assert (manifest.health_command, manifest.opt_in, manifest.platforms) == (
        ("codegraph --version",),
        False,
        (),
    )


@pytest.mark.parametrize(
    "data",
    [
        pytest.param(
            {"api_version": "1", "version": "1", "provides": [], "health_command": []},
            id="missing_id",
        ),
        pytest.param(
            {"id": "m", "api_version": "1", "version": "1", "health_command": []},
            id="missing_provides",
        ),
        pytest.param(
            {"id": "m", "api_version": "1", "version": "1", "provides": []},
            id="missing_health_command",
        ),
        pytest.param(
            {"id": "m", "api_version": 1, "version": "1", "provides": [], "health_command": []},
            id="api_version_not_string",
        ),
        pytest.param(
            {
                "id": "m",
                "api_version": "1",
                "version": "1",
                "provides": "code.search",
                "health_command": [],
            },
            id="provides_not_list",
        ),
        pytest.param(
            {
                "id": "m",
                "api_version": "1",
                "version": "1",
                "provides": [],
                "health_command": [],
                "opt_in": "yes",
            },
            id="opt_in_not_bool",
        ),
    ],
)
def test_module_manifest_from_mapping_invalid_raises_value_error(data):
    with pytest.raises(ValueError):
        ModuleManifest.from_mapping(data)
