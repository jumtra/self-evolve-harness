from __future__ import annotations

import json
import subprocess
from pathlib import Path

from seh.contracts import RunContext, RunResult, TerminalState
from seh.contracts.schema import validate
from seh.contracts.state import UnitState
from seh.runtime.agent_runner import RunnerRegistry
from seh.runtime.checkpoint import CheckpointStore
from seh.runtime.gate import final_output_to_dict
from seh.runtime.managed import ManagedOptions, run_managed
from seh.runtime.runners.fake import FakeCliRunner

OPTIONS = ManagedOptions(
    host="claude",
    max_parallel=3,
    max_attempts_per_unit=3,
    max_seconds_per_unit=60,
    max_total_seconds=600,
    unattended=False,
)


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    ).stdout


async def test_three_posts_with_one_local_repair_pass_through_the_gate(
    repo: Path, tmp_path: Path
) -> None:
    task_file = tmp_path / "task.json"
    task_file.write_text(
        json.dumps(
            {
                "task": {
                    "id": "x-posts",
                    "goal": "X 投稿を 3 本作る",
                    "acceptance": ["posts/a.txt posts/b.txt posts/c.txt がある"],
                    "risk": "R0",
                    "mode": "managed",
                },
                "units": [
                    {
                        "node_id": "post_a",
                        "kind": "worker",
                        "depends_on": [],
                        "inputs": {},
                        "outputs_schema": "schema://post",
                        "write_allowlist": ["posts/a.txt"],
                        "checks": ["check_a"],
                        "risk": "R0",
                        "prompt": "posts/a.txt に A を書く",
                    },
                    {
                        "node_id": "post_b",
                        "kind": "worker",
                        "depends_on": [],
                        "inputs": {},
                        "outputs_schema": "schema://post",
                        "write_allowlist": ["posts/b.txt"],
                        "checks": ["check_b"],
                        "risk": "R0",
                        "prompt": "posts/b.txt に B を書く",
                    },
                    {
                        "node_id": "post_c",
                        "kind": "worker",
                        "depends_on": [],
                        "inputs": {},
                        "outputs_schema": "schema://post",
                        "write_allowlist": ["posts/c.txt"],
                        "checks": ["check_c"],
                        "risk": "R0",
                        "prompt": "posts/c.txt に C を書く",
                    },
                    {
                        "node_id": "gate",
                        "kind": "gate",
                        "depends_on": ["post_a", "post_b", "post_c"],
                        "inputs": {"a": "", "b": "", "c": ""},
                        "outputs_schema": None,
                        "write_allowlist": [],
                        "checks": [],
                        "risk": "R0",
                    },
                ],
                "edges": [
                    {
                        "from_node": "post_a",
                        "from_output": "out",
                        "to_node": "gate",
                        "to_input": "a",
                    },
                    {
                        "from_node": "post_b",
                        "from_output": "out",
                        "to_node": "gate",
                        "to_input": "b",
                    },
                    {
                        "from_node": "post_c",
                        "from_output": "out",
                        "to_node": "gate",
                        "to_input": "c",
                    },
                ],
                "checks": {
                    "check_a": {
                        "tool": "tests.run",
                        "args": {
                            "argv": [
                                "python3",
                                "-c",
                                "import sys; sys.exit(0 if "
                                "open('posts/a.txt').read() == 'A\\n' else 1)",
                            ]
                        },
                    },
                    "check_b": {
                        "tool": "tests.run",
                        "args": {
                            "argv": [
                                "python3",
                                "-c",
                                "import sys; sys.exit(0 if "
                                "open('posts/b.txt').read() == 'B\\n' else 1)",
                            ]
                        },
                    },
                    "check_c": {
                        "tool": "tests.run",
                        "args": {
                            "argv": [
                                "python3",
                                "-c",
                                "import sys; sys.exit(0 if "
                                "open('posts/c.txt').read() == 'C\\n' else 1)",
                            ]
                        },
                    },
                },
            }
        )
    )
    writes = {"post_a": "A\n", "post_b": "B\n", "post_c": "C\n"}
    seen: dict[str, int] = {}

    def behave(prompt: str, context: RunContext) -> RunResult:
        node = context.cwd.name
        seen[node] = seen.get(node, 0) + 1
        text = "間違い\n" if node == "post_b" and seen[node] == 1 else writes[node]
        target = context.cwd / "posts" / f"{node[-1]}.txt"
        target.parent.mkdir(exist_ok=True)
        target.write_text(text)
        return RunResult(
            "r", "claude", TerminalState.SUCCESS, 0, "完了しました", None, (), None, None
        )

    runner = FakeCliRunner("claude", behave)
    registry = RunnerRegistry()
    registry.register(runner)
    head_before = _git(repo, "rev-parse", "HEAD")
    status_before = _git(repo, "status", "--porcelain")

    final = await run_managed(repo, task_file, OPTIONS, runners=registry, run_id="r1")

    assert final.status is UnitState.PASSED
    assert final.requires_human_approval is True
    assert final.changed_files == ("posts/a.txt", "posts/b.txt", "posts/c.txt")
    assert final.evidence_refs
    assert seen == {"post_a": 1, "post_b": 2, "post_c": 1}
    assert len(runner.calls) == 4
    validate("final_output", final_output_to_dict(final))
    # 統合は専用ブランチだけに入り、ユーザーの作業ツリーと HEAD は不変
    assert _git(repo, "show", "seh/r1/integration:posts/b.txt") == "B\n"
    assert _git(repo, "rev-parse", "HEAD") == head_before
    assert _git(repo, "status", "--porcelain") == status_before
    assert _git(repo, "branch", "--show-current").strip() == "main"
    # Evidence bundle と trace
    bundle = repo / ".harness" / "artifacts" / "r1"
    assert (bundle / "verdict-post_b.json").is_file()
    assert (bundle / "final_output.json").is_file()
    assert (repo / ".harness" / "state" / "runs" / "r1" / "trace.jsonl").is_file()
    # worktree は削除され、ユニットブランチは残る
    assert not (repo / ".harness" / "state" / "worktrees" / "r1" / "post_a").exists()
    assert "seh/r1/post_a" in _git(repo, "branch", "--list", "seh/r1/*")
    loaded = CheckpointStore(repo, "r1").load()
    assert loaded is not None
    assert set(loaded.state.states.values()) == {UnitState.PASSED}
    assert len(loaded.attempts["post_b"]) == 2


async def test_always_wrong_worker_fails_after_three_attempts_and_blocks_gate(
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
                    "c": {
                        "tool": "tests.run",
                        "args": {
                            "argv": [
                                "python3",
                                "-c",
                                "import sys; sys.exit(0 if open('a.txt').read() == 'OK\\n' else 1)",
                            ]
                        },
                    }
                },
            }
        )
    )

    def behave(prompt: str, context: RunContext) -> RunResult:
        (context.cwd / "a.txt").write_text("NG\n")
        # Runner は成功を自己申告するが、独立 Checker が不合格にする（T07）
        return RunResult(
            "r",
            "claude",
            TerminalState.SUCCESS,
            0,
            "すべて完了。テストも通りました",
            None,
            (),
            None,
            None,
        )

    runner = FakeCliRunner("claude", behave)
    registry = RunnerRegistry()
    registry.register(runner)

    final = await run_managed(repo, task_file, OPTIONS, runners=registry, run_id="r2")

    assert final.status is UnitState.FAILED
    assert len(runner.calls) == 3
    loaded = CheckpointStore(repo, "r2").load()
    assert loaded is not None
    assert loaded.state.states == {"w": UnitState.FAILED, "gate": UnitState.BLOCKED}
    assert loaded.state.outcomes["gate"].reason == "UPSTREAM_FAILED:w"
    # 失敗ユニットは統合ブランチへ入らない
    assert "seh/r2/integration" not in _git(repo, "branch", "--list")


async def test_worker_without_checks_never_passes(repo: Path, tmp_path: Path) -> None:
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
                        "checks": [],
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

    def behave(prompt: str, context: RunContext) -> RunResult:
        (context.cwd / "a.txt").write_text("OK\n")
        return RunResult("r", "claude", TerminalState.SUCCESS, 0, "完了", None, (), None, None)

    registry = RunnerRegistry()
    registry.register(FakeCliRunner("claude", behave))

    final = await run_managed(repo, task_file, OPTIONS, runners=registry, run_id="r3")

    assert final.status is UnitState.FAILED
    loaded = CheckpointStore(repo, "r3").load()
    assert loaded is not None
    assert loaded.attempts["w"][0].reason_code == "NO_CHECKS"
