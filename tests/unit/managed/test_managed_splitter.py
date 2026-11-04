from __future__ import annotations

import json
from pathlib import Path

import pytest

from seh.contracts import RunContext, RunResult, TaskSpec, TerminalState
from seh.contracts.task import RiskRank
from seh.knowledge import VerifiedConstraint
from seh.runtime.runners.fake import FakeCliRunner
from seh.runtime.splitter import SplitError, split_with_agent

TASK = TaskSpec("t1", "投稿 A と B を作る", ("a.txt と b.txt がある",), RiskRank.R0, "managed")
VALID_PLAN = {
    "units": [
        {
            "node_id": "w",
            "kind": "worker",
            "depends_on": [],
            "inputs": {},
            "outputs_schema": "schema://w",
            "write_allowlist": ["a.txt"],
            "checks": ["c"],
            "risk": "R0",
            "prompt": "a.txt を作る",
            "host": None,
        },
        {
            "node_id": "g",
            "kind": "gate",
            "depends_on": ["w"],
            "inputs": {"x": ""},
            "outputs_schema": None,
            "write_allowlist": [],
            "checks": [],
            "risk": "R0",
            "prompt": None,
            "host": None,
        },
    ],
    "edges": [{"from_node": "w", "from_output": "out", "to_node": "g", "to_input": "x"}],
    "checks": {"c": {"tool": "tests.run", "args": {"argv": ["python3", "-V"]}}},
}
CONSTRAINT = VerifiedConstraint(
    "c1",
    "generated/ 配下は編集しない",
    ("**",),
    "rec1",
    (),
    "2026-11-01T00:00:00+00:00",
    None,
    "active",
)


def _ok(text: str) -> RunResult:
    return RunResult("r", "fake", TerminalState.SUCCESS, 0, text, None, (), None, None)


async def test_valid_plan_becomes_units_edges_and_checks(tmp_path: Path) -> None:
    runner = FakeCliRunner("fake", [_ok(json.dumps(VALID_PLAN))])

    plan = await split_with_agent(TASK, runner, root=tmp_path, constraints=[])

    assert [u.node_id for u in plan.units] == ["w", "g"]
    assert plan.edges[0].to_node == "g"
    assert plan.checks["c"].tool == "tests.run"
    assert len(runner.calls) == 1


async def test_splitter_runs_read_only_in_repo_root(tmp_path: Path) -> None:
    runner = FakeCliRunner("fake", [_ok(json.dumps(VALID_PLAN))])

    await split_with_agent(TASK, runner, root=tmp_path, constraints=[])

    _, context = runner.calls[0]
    assert isinstance(context, RunContext)
    assert context.permissions_profile == "read-only"
    assert context.cwd == tmp_path


async def test_prompt_contains_goal_acceptance_and_constraint_statements(tmp_path: Path) -> None:
    runner = FakeCliRunner("fake", [_ok(json.dumps(VALID_PLAN))])

    await split_with_agent(TASK, runner, root=tmp_path, constraints=[CONSTRAINT])

    prompt = runner.calls[0][0]
    assert "投稿 A と B を作る" in prompt
    assert "a.txt と b.txt がある" in prompt
    assert "generated/ 配下は編集しない" in prompt


async def test_invalid_graph_gets_one_retry_with_error_codes(tmp_path: Path) -> None:
    bad = json.loads(json.dumps(VALID_PLAN))
    bad["units"][0]["write_allowlist"] = []
    runner = FakeCliRunner("fake", [_ok(json.dumps(bad)), _ok(json.dumps(VALID_PLAN))])

    plan = await split_with_agent(TASK, runner, root=tmp_path, constraints=[])

    assert len(runner.calls) == 2
    assert "EMPTY_WRITE_ALLOWLIST:w" in runner.calls[1][0]
    assert [u.node_id for u in plan.units] == ["w", "g"]


async def test_still_invalid_after_retry_is_invalid_split(tmp_path: Path) -> None:
    bad = json.loads(json.dumps(VALID_PLAN))
    bad["units"][0]["write_allowlist"] = []
    runner = FakeCliRunner("fake", [_ok(json.dumps(bad)), _ok(json.dumps(bad))])

    with pytest.raises(SplitError) as excinfo:
        await split_with_agent(TASK, runner, root=tmp_path, constraints=[])

    assert excinfo.value.code == "INVALID_SPLIT"
    assert excinfo.value.blocked is False
    assert len(runner.calls) == 2


async def test_unparseable_output_is_invalid_split(tmp_path: Path) -> None:
    runner = FakeCliRunner("fake", lambda prompt, ctx: _ok("分割できませんでした"))

    with pytest.raises(SplitError) as excinfo:
        await split_with_agent(TASK, runner, root=tmp_path, constraints=[])

    assert excinfo.value.code == "INVALID_SPLIT"


async def test_policy_blocked_runner_is_reported_as_blocked(tmp_path: Path) -> None:
    blocked = RunResult(
        "r", "fake", TerminalState.POLICY_BLOCKED, None, None, None, (), None, "AGY_BLOCKED"
    )
    runner = FakeCliRunner("fake", [blocked])

    with pytest.raises(SplitError) as excinfo:
        await split_with_agent(TASK, runner, root=tmp_path, constraints=[])

    assert excinfo.value.code == "POLICY_BLOCKED"
    assert excinfo.value.blocked is True
