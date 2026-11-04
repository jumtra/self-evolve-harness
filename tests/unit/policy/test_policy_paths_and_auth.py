from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from seh.contracts import ApprovalToken
from seh.policy import (
    ALLOW_ALL,
    Action,
    Policy,
    action_digest,
    is_protected_path,
    is_sensitive_path,
    is_tool_config_path,
)


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        (".env", True),
        (".ENV", True),
        ("app/.env.production", True),
        ("certs/server.pem", True),
        ("id.key", True),
        ("aws_credentials", True),
        ("my-Secret.txt", True),
        (".env.example", False),
        (".env.sample", False),
        (".env.template", False),
        ("src/main.py", False),
    ],
)
def test_is_sensitive_path_matches_basename(path: str, expected: bool) -> None:
    assert is_sensitive_path(path) is expected


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("biome.json", True),
        ("biome.jsonc", True),
        (".mypy.ini", True),
        (".stylelintrc.json", True),
        (".clang-format", True),
        (".clang-tidy", True),
        ("Directory.Build.props", True),
        (".tflint.hcl", True),
        ("sub/tsconfig.build.json", True),
        ("src/main.py", False),
    ],
)
def test_is_tool_config_path_matches_union_of_known_configs(path: str, expected: bool) -> None:
    assert is_tool_config_path(path) is expected


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        (".harness/backups/2026/x.tar", True),
        (".harness/ownership.json", True),
        (".harness/generated.lock.json", True),
        (".harness/policy", True),
        ("apps/x/.claude/settings.json", True),
        ("src/seh/other.py", False),
    ],
)
def test_is_protected_path_covers_harness_state_and_nested_settings(
    path: str, expected: bool
) -> None:
    assert is_protected_path(path) is expected


def test_is_protected_path_absolute_inside_root_is_relativized(tmp_path: Path) -> None:
    target = str(tmp_path / ".harness" / "config.toml")

    assert is_protected_path(target, root=tmp_path) is True


def test_is_protected_path_absolute_inside_root_normal_file_is_not_protected(
    tmp_path: Path,
) -> None:
    target = str(tmp_path / "src" / "a.py")

    assert is_protected_path(target, root=tmp_path) is False


def test_is_protected_path_absolute_outside_root_is_protected(tmp_path: Path) -> None:
    assert is_protected_path("/etc/passwd", root=tmp_path) is True


def test_authorize_tool_empty_allowlist_is_denied() -> None:
    decision = Policy().authorize_tool("anything")

    assert (decision.allowed, decision.reason_code) == (False, "TOOL_NOT_ALLOWED")


def test_authorize_tool_allow_all_is_allowed() -> None:
    policy = Policy(tool_allowlist=ALLOW_ALL)

    assert policy.authorize_tool("anything").allowed is True


def test_authorize_command_full_path_with_only_basename_allowlisted_is_denied() -> None:
    policy = Policy(command_allowlist=frozenset({"git"}))

    decision = policy.authorize_command(["/tmp/evil/git", "status"])

    assert (decision.allowed, decision.reason_code) == (False, "COMMAND_NOT_ALLOWED")


def test_authorize_command_full_path_exact_match_is_allowed() -> None:
    policy = Policy(command_allowlist=frozenset({"/usr/bin/git"}))

    assert policy.authorize_command(["/usr/bin/git", "status"]).allowed is True


def test_action_digest_is_stable_and_differs_per_action() -> None:
    a = Action(kind="command", target="rm -rf build")
    b = Action(kind="command", target="rm -rf dist")

    assert (action_digest(a) == action_digest(a), action_digest(a) == action_digest(b)) == (
        True,
        False,
    )


def test_authorize_token_bound_to_other_action_is_denied() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    approved = Action(kind="command", target="rm -rf build")
    attempted = Action(kind="command", target="rm -rf /srv")
    token = ApprovalToken(
        id="t1",
        scope=("command:*",),
        target_digest=action_digest(approved),
        expires_at=now + timedelta(hours=1),
        issued_by="human",
    )

    decision = Policy().authorize(
        attempted, unattended=True, token=token, token_scope="command:rm", now=now
    )

    assert (decision.allowed, decision.reason_code) == (False, "R2_REQUIRES_APPROVAL")


def test_authorize_token_bound_to_same_action_is_allowed() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    action = Action(kind="command", target="rm -rf build")
    token = ApprovalToken(
        id="t1",
        scope=("command:*",),
        target_digest=action_digest(action),
        expires_at=now + timedelta(hours=1),
        issued_by="human",
    )

    decision = Policy().authorize(
        action, unattended=True, token=token, token_scope="command:rm", now=now
    )

    assert decision.allowed is True
