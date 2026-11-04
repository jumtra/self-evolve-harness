from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

import pytest

from seh.cli import main
from seh.contracts import RunContext, RunResult, TerminalState
from seh.contracts.state import UnitState
from seh.knowledge import VerifiedConstraint, append_constraint
from seh.runtime.agent_runner import RunnerRegistry
from seh.runtime.checkpoint import CheckpointStore
from seh.runtime.managed import ManagedOptions, run_managed
from seh.runtime.runners.fake import FakeCliRunner


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    ).stdout


async def test_budget_stop_leaves_pending_and_resume_skips_passed_nodes(
    repo: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    task_file = tmp_path / "task.json"
    task_file.write_text(
        json.dumps(
            {
                "task": {
                    "id": "t",
                    "goal": "2 ファイルを順に作る",
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
                        "write_allowlist": ["w1.txt"],
                        "checks": ["c1"],
                        "risk": "R0",
                    },
                    {
                        "node_id": "w2",
                        "kind": "worker",
                        "depends_on": ["w1"],
                        "inputs": {"prev": ""},
                        "outputs_schema": "schema://w",
                        "write_allowlist": ["w2.txt"],
                        "checks": ["c2"],
                        "risk": "R0",
                    },
                    {
                        "node_id": "gate",
                        "kind": "gate",
                        "depends_on": ["w2"],
                        "inputs": {"x": ""},
                        "outputs_schema": None,
                        "write_allowlist": [],
                        "checks": [],
                        "risk": "R0",
                    },
                ],
                "edges": [
                    {"from_node": "w1", "from_output": "out", "to_node": "w2", "to_input": "prev"},
                    {"from_node": "w2", "from_output": "out", "to_node": "gate", "to_input": "x"},
                ],
                "checks": {
                    "c1": {
                        "tool": "tests.run",
                        "args": {"argv": ["python3", "-c", "open('w1.txt')"]},
                    },
                    "c2": {
                        "tool": "tests.run",
                        "args": {"argv": ["python3", "-c", "open('w2.txt')"]},
                    },
                },
            }
        )
    )

    def slow_first(prompt: str, context: RunContext) -> RunResult:
        time.sleep(1.2)  # max_total_seconds=1 を超えさせ、次ノード開始前に予算停止させる
        (context.cwd / f"{context.cwd.name}.txt").write_text("done\n")
        return RunResult("r", "claude", TerminalState.SUCCESS, 0, "完了", None, (), None, None)

    first_runner = FakeCliRunner("claude", slow_first)
    first_registry = RunnerRegistry()
    first_registry.register(first_runner)
    short = ManagedOptions("claude", 1, 3, 60, 1, False)

    stopped = await run_managed(repo, task_file, short, runners=first_registry, run_id="r1")

    assert stopped.status is UnitState.BLOCKED
    assert any("BUDGET_EXCEEDED:time" in r for r in stopped.remaining_risks)
    saved = CheckpointStore(repo, "r1").load()
    assert saved is not None
    assert saved.state.states == {
        "w1": UnitState.PASSED,
        "w2": UnitState.PENDING,
        "gate": UnitState.PENDING,
    }
    assert main(["work", "status", "r1", "--root", str(repo)]) == 0
    assert "PENDING" in capsys.readouterr().out

    def fast(prompt: str, context: RunContext) -> RunResult:
        assert (context.cwd / "w1.txt").read_text() == "done\n"
        (context.cwd / f"{context.cwd.name}.txt").write_text("done\n")
        return RunResult("r", "claude", TerminalState.SUCCESS, 0, "完了", None, (), None, None)

    second_runner = FakeCliRunner("claude", fast)
    second_registry = RunnerRegistry()
    second_registry.register(second_runner)
    long = ManagedOptions("claude", 1, 3, 60, 3600, False)

    final = await run_managed(
        repo, task_file, long, runners=second_registry, run_id="r1", resume=True
    )

    assert final.status is UnitState.PASSED
    assert [ctx.cwd.name for _, ctx in second_runner.calls] == ["w2"]
    assert final.changed_files == ("w1.txt", "w2.txt")
    assert len(first_runner.calls) == 1


async def test_splitter_generates_graph_with_learning_edge_and_workers_run(
    repo: Path, tmp_path: Path
) -> None:
    append_constraint(
        repo,
        VerifiedConstraint(
            "c1",
            "generated/ 配下は編集しない",
            ("**",),
            "rec1",
            (),
            "2026-11-01T00:00:00+00:00",
            None,
            "active",
        ),
    )
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-q", "-m", "c")
    task_file = tmp_path / "task.json"
    task_file.write_text(
        json.dumps(
            {
                "task": {
                    "id": "t",
                    "goal": "a.txt を作る",
                    "acceptance": ["a.txt がある"],
                    "risk": "R0",
                    "mode": "managed",
                },
                "units": None,
                "edges": None,
                "checks": {},
            }
        )
    )
    plan = {
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
                "node_id": "gate",
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
        "edges": [{"from_node": "w", "from_output": "out", "to_node": "gate", "to_input": "x"}],
        "checks": {
            "c": {"tool": "tests.run", "args": {"argv": ["python3", "-c", "open('a.txt')"]}}
        },
    }

    def behave(prompt: str, context: RunContext) -> RunResult:
        if context.permissions_profile == "read-only":
            return RunResult(
                "r", "claude", TerminalState.SUCCESS, 0, json.dumps(plan), None, (), None, None
            )
        (context.cwd / "a.txt").write_text("OK\n")
        return RunResult("r", "claude", TerminalState.SUCCESS, 0, "完了", None, (), None, None)

    runner = FakeCliRunner("claude", behave)
    registry = RunnerRegistry()
    registry.register(runner)
    options = ManagedOptions("claude", 2, 3, 60, 600, False)

    final = await run_managed(repo, task_file, options, runners=registry, run_id="r2")

    assert final.status is UnitState.PASSED
    assert "generated/ 配下は編集しない" in runner.calls[0][0]
    assert runner.calls[0][1].cwd != repo
    assert runner.calls[0][1].cwd.is_relative_to(repo / ".harness" / "state" / "worktrees")
    assert [ctx.permissions_profile for _, ctx in runner.calls] == ["read-only", "workspace-write"]
    # splitter はファイルを書かず、生成された計画は再開用に保存される
    assert _git(repo, "status", "--porcelain") == ""
    assert (repo / ".harness" / "state" / "runs" / "r2" / "plan.json").is_file()


async def test_invalid_split_is_reported_as_failed_output(repo: Path, tmp_path: Path) -> None:
    task_file = tmp_path / "task.json"
    task_file.write_text(
        json.dumps(
            {
                "task": {"id": "t", "goal": "g", "acceptance": [], "risk": "R0", "mode": "managed"},
                "units": None,
                "edges": None,
                "checks": {},
            }
        )
    )
    runner = FakeCliRunner(
        "claude",
        lambda prompt, ctx: RunResult(
            "r", "claude", TerminalState.SUCCESS, 0, "分割不能", None, (), None, None
        ),
    )
    registry = RunnerRegistry()
    registry.register(runner)
    options = ManagedOptions("claude", 2, 3, 60, 600, False)

    final = await run_managed(repo, task_file, options, runners=registry, run_id="r3")

    assert final.status is UnitState.FAILED
    assert "INVALID_SPLIT" in final.summary
    assert all(ctx.permissions_profile == "read-only" for _, ctx in runner.calls)


def test_work_run_cli_prints_final_output_and_exits_zero_on_passed(
    repo: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    import seh.commands.work as work

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
        return RunResult("r", "claude", TerminalState.SUCCESS, 0, "完了", None, (), None, None)

    registry = RunnerRegistry()
    registry.register(FakeCliRunner("claude", behave))
    monkeypatch.setattr(work, "REGISTRY", registry)

    code = main(
        [
            "work",
            "run",
            "--task",
            str(task_file),
            "--root",
            str(repo),
            "--mode",
            "managed",
            "--host",
            "claude",
        ]
    )

    out = capsys.readouterr().out
    assert code == 0
    assert '"status": "PASSED"' in out
    assert "run_id" in out
