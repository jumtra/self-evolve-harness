from __future__ import annotations

import json
from pathlib import Path

import pytest

from seh.contracts.task import NodeKind, RiskRank
from seh.runtime.splitter import TaskFileError, load_task_file, plan_from_task_file


def test_explicit_units_and_edges_build_a_graph(tmp_path: Path) -> None:
    task_file = tmp_path / "task.json"
    task_file.write_text(
        json.dumps(
            {
                "task": {
                    "id": "t1",
                    "goal": "投稿を作る",
                    "acceptance": ["a.txt がある"],
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
                        "node_id": "g",
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
                    {"from_node": "w", "from_output": "out", "to_node": "g", "to_input": "x"}
                ],
                "checks": {"c": {"tool": "tests.run", "args": {"argv": ["python3", "-V"]}}},
            }
        )
    )

    graph = plan_from_task_file(task_file)
    loaded = load_task_file(task_file)

    assert [n.node_id for n in graph.nodes] == ["w", "g"]
    assert graph.nodes[0].kind is NodeKind.WORKER
    assert loaded.task.risk is RiskRank.R0
    assert loaded.checks["c"].tool == "tests.run"
    assert loaded.base is None


def test_units_null_means_splitter_is_needed(tmp_path: Path) -> None:
    task_file = tmp_path / "task.json"
    task_file.write_text(
        json.dumps(
            {
                "task": {
                    "id": "t1",
                    "goal": "g",
                    "acceptance": [],
                    "risk": "R0",
                    "mode": "managed",
                },
                "units": None,
                "edges": None,
                "checks": {},
            }
        )
    )

    loaded = load_task_file(task_file)

    assert loaded.units is None
    with pytest.raises(TaskFileError):
        plan_from_task_file(task_file)


def test_schema_violation_raises_task_file_error(tmp_path: Path) -> None:
    task_file = tmp_path / "task.json"
    task_file.write_text(json.dumps({"task": {"id": "t1"}}))

    with pytest.raises(TaskFileError):
        load_task_file(task_file)
