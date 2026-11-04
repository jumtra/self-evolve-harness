from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from seh.contracts import RunContext, RunResult, TerminalState
from seh.contracts.state import UnitState
from seh.runtime.agent_runner import RunnerRegistry
from seh.runtime.checkpoint import CheckpointStore
from seh.runtime.managed import ManagedOptions, run_managed
from seh.runtime.runners.defaults import default_registry
from seh.runtime.runners.fake import FakeCliRunner
from seh.runtime.worktree import WorktreeError

OPTIONS = ManagedOptions(
    host="claude",
    max_parallel=3,
    max_attempts_per_unit=3,
    max_seconds_per_unit=60,
    max_total_seconds=600,
    unattended=True,
)


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    ).stdout


async def test_write_outside_allowlist_is_scope_violation_and_fails_when_not_fixed(
    repo: Path, tmp_path: Path
) -> None:
    task_file = tmp_path / "task.json"
    task_file.write_text(
        json.dumps(
            {
                "task": {
                    "id": "t",
                    "goal": "a を作る",
                    "acceptance": [],
                    "risk": "R0",
                    "mode": "managed",
                },
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
                    },
                    {
                        "node_id": "gate",
                        "kind": "gate",
                        "depends_on": ["w"],
                        "inputs": {"x": ""},
                        "outputs_schema": None,
                        "write_allowlist": [],
                        "checks": [],
                        "risk": "R0",
                    },
                ],
                "edges": [
                    {"from_node": "w", "from_output": "out", "to_node": "gate", "to_input": "x"}
                ],
                "checks": {
                    "c": {"tool": "tests.run", "args": {"argv": ["python3", "-c", "open('a.txt')"]}}
                },
            }
        )
    )

    def behave(prompt: str, context: RunContext) -> RunResult:
        (context.cwd / "a.txt").write_text("OK\n")
        (context.cwd / "oops.txt").write_text("範囲外\n")
        return RunResult("r", "claude", TerminalState.SUCCESS, 0, "完了", None, (), None, None)

    runner = FakeCliRunner("claude", behave)
    registry = RunnerRegistry()
    registry.register(runner)

    final = await run_managed(repo, task_file, OPTIONS, runners=registry, run_id="r1")

    assert final.status is UnitState.FAILED
    assert len(runner.calls) == 3
    # 2 回目のプロンプトに違反理由と許可範囲が修正入力として渡る
    assert "SCOPE_VIOLATION" in runner.calls[1][0]
    assert "a.txt" in runner.calls[1][0]
    loaded = CheckpointStore(repo, "r1").load()
    assert loaded is not None
    assert [a.reason_code for a in loaded.attempts["w"]] == ["SCOPE_VIOLATION"] * 3


async def test_same_line_changed_by_two_workers_fails_gate_with_merge_conflict(
    repo: Path, tmp_path: Path
) -> None:
    task_file = tmp_path / "task.json"
    task_file.write_text(
        json.dumps(
            {
                "task": {
                    "id": "t",
                    "goal": "shared.txt を直す",
                    "acceptance": [],
                    "risk": "R0",
                    "mode": "managed",
                },
                "units": [
                    {
                        "node_id": "w1",
                        "kind": "worker",
                        "depends_on": [],
                        "inputs": {},
                        "outputs_schema": "schema://w",
                        "write_allowlist": ["shared.txt"],
                        "checks": ["c"],
                        "risk": "R0",
                    },
                    {
                        "node_id": "w2",
                        "kind": "worker",
                        "depends_on": [],
                        "inputs": {},
                        "outputs_schema": "schema://w",
                        "write_allowlist": ["shared.txt"],
                        "checks": ["c"],
                        "risk": "R0",
                    },
                    {
                        "node_id": "gate",
                        "kind": "gate",
                        "depends_on": ["w1", "w2"],
                        "inputs": {"a": "", "b": ""},
                        "outputs_schema": None,
                        "write_allowlist": [],
                        "checks": [],
                        "risk": "R0",
                    },
                ],
                "edges": [
                    {"from_node": "w1", "from_output": "out", "to_node": "gate", "to_input": "a"},
                    {"from_node": "w2", "from_output": "out", "to_node": "gate", "to_input": "b"},
                ],
                "checks": {
                    "c": {
                        "tool": "tests.run",
                        "args": {"argv": ["python3", "-c", "open('shared.txt')"]},
                    }
                },
            }
        )
    )

    def behave(prompt: str, context: RunContext) -> RunResult:
        (context.cwd / "shared.txt").write_text(f"{context.cwd.name} の変更\n")
        return RunResult("r", "claude", TerminalState.SUCCESS, 0, "完了", None, (), None, None)

    registry = RunnerRegistry()
    registry.register(FakeCliRunner("claude", behave))

    final = await run_managed(repo, task_file, OPTIONS, runners=registry, run_id="r2")

    assert final.status is UnitState.FAILED
    assert "MERGE_CONFLICT:w2" in final.summary
    merged = _git(repo, "show", "seh/r2/integration:shared.txt")
    assert merged == "w1 の変更\n"
    assert "<<<<<<<" not in merged
    loaded = CheckpointStore(repo, "r2").load()
    assert loaded is not None
    assert loaded.state.states["gate"] is UnitState.FAILED
    assert loaded.state.outcomes["gate"].reason == "MERGE_CONFLICT:w2"


async def test_integrated_change_to_protected_config_waits_for_approval_even_unattended(
    repo: Path, tmp_path: Path
) -> None:
    task_file = tmp_path / "task.json"
    task_file.write_text(
        json.dumps(
            {
                "task": {
                    "id": "t",
                    "goal": "設定を直す",
                    "acceptance": [],
                    "risk": "R0",
                    "mode": "managed",
                },
                "units": [
                    {
                        "node_id": "w",
                        "kind": "worker",
                        "depends_on": [],
                        "inputs": {},
                        "outputs_schema": "schema://w",
                        "write_allowlist": [".claude/settings.json"],
                        "checks": ["c"],
                        "risk": "R0",
                    },
                    {
                        "node_id": "gate",
                        "kind": "gate",
                        "depends_on": ["w"],
                        "inputs": {"x": ""},
                        "outputs_schema": None,
                        "write_allowlist": [],
                        "checks": [],
                        "risk": "R0",
                    },
                ],
                "edges": [
                    {"from_node": "w", "from_output": "out", "to_node": "gate", "to_input": "x"}
                ],
                "checks": {
                    "c": {
                        "tool": "tests.run",
                        "args": {"argv": ["python3", "-c", "open('.claude/settings.json')"]},
                    }
                },
            }
        )
    )

    def behave(prompt: str, context: RunContext) -> RunResult:
        (context.cwd / ".claude").mkdir(exist_ok=True)
        (context.cwd / ".claude" / "settings.json").write_text("{}\n")
        return RunResult("r", "claude", TerminalState.SUCCESS, 0, "完了", None, (), None, None)

    registry = RunnerRegistry()
    registry.register(FakeCliRunner("claude", behave))

    final = await run_managed(repo, task_file, OPTIONS, runners=registry, run_id="r3")

    assert final.status is UnitState.WAITING_APPROVAL
    assert final.requires_human_approval is True
    assert final.changed_files == (".claude/settings.json",)


async def test_antigravity_host_is_policy_blocked_without_calling_other_runners(
    repo: Path, tmp_path: Path
) -> None:
    task_file = tmp_path / "task.json"
    task_file.write_text(
        json.dumps(
            {
                "task": {
                    "id": "t",
                    "goal": "a を作る",
                    "acceptance": [],
                    "risk": "R0",
                    "mode": "managed",
                },
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
                    },
                    {
                        "node_id": "gate",
                        "kind": "gate",
                        "depends_on": ["w"],
                        "inputs": {"x": ""},
                        "outputs_schema": None,
                        "write_allowlist": [],
                        "checks": [],
                        "risk": "R0",
                    },
                ],
                "edges": [
                    {"from_node": "w", "from_output": "out", "to_node": "gate", "to_input": "x"}
                ],
                "checks": {
                    "c": {"tool": "tests.run", "args": {"argv": ["python3", "-c", "open('a.txt')"]}}
                },
            }
        )
    )
    bystander = FakeCliRunner(
        "claude",
        lambda prompt, ctx: RunResult(
            "r", "claude", TerminalState.SUCCESS, 0, "x", None, (), None, None
        ),
    )
    registry = default_registry()
    registry.register(bystander)
    options = ManagedOptions("antigravity", 3, 3, 60, 600, True)

    final = await run_managed(repo, task_file, options, runners=registry, run_id="r4")

    assert final.status is UnitState.BLOCKED
    assert "POLICY_BLOCKED" in final.summary
    assert bystander.calls == []


async def test_dirty_base_stops_with_error(repo: Path, tmp_path: Path) -> None:
    task_file = tmp_path / "task.json"
    task_file.write_text(
        json.dumps(
            {
                "task": {"id": "t", "goal": "g", "acceptance": [], "risk": "R0", "mode": "managed"},
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
                    },
                    {
                        "node_id": "gate",
                        "kind": "gate",
                        "depends_on": ["w"],
                        "inputs": {"x": ""},
                        "outputs_schema": None,
                        "write_allowlist": [],
                        "checks": [],
                        "risk": "R0",
                    },
                ],
                "edges": [
                    {"from_node": "w", "from_output": "out", "to_node": "gate", "to_input": "x"}
                ],
                "checks": {},
            }
        )
    )
    (repo / "shared.txt").write_text("未コミットの変更\n")
    runner = FakeCliRunner("claude", [])
    registry = RunnerRegistry()
    registry.register(runner)

    with pytest.raises(WorktreeError, match="DIRTY_BASE"):
        await run_managed(repo, task_file, OPTIONS, runners=registry, run_id="r5")

    assert runner.calls == []
