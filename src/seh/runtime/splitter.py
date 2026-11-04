"""タスクファイルの読み込みと、CLI による DAG 分割（splitter）。splitter は read-only で動く。"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from seh.contracts import (
    CliAgentRunner,
    Edge,
    NodeKind,
    RiskRank,
    RunContext,
    SchemaError,
    TaskLimits,
    TaskSpec,
    TerminalState,
    WorkUnit,
    load_schema,
    validate,
)
from seh.knowledge import VerifiedConstraint
from seh.runtime.graph import GraphError, WorkflowGraph
from seh.runtime.output import run_with_output_contract
from seh.runtime.process import DEFAULT_ENV_ALLOWLIST

_BLOCKED_TERMINALS = frozenset(
    {TerminalState.POLICY_BLOCKED, TerminalState.BLOCKED_AUTH, TerminalState.UNSUPPORTED}
)


class TaskFileError(ValueError):
    pass


class SplitError(Exception):
    def __init__(self, code: str, message: str, *, blocked: bool = False) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.blocked = blocked


@dataclass(frozen=True)
class CheckSpec:
    tool: str
    args: Mapping[str, object]


@dataclass(frozen=True)
class SplitPlan:
    units: tuple[WorkUnit, ...]
    edges: tuple[Edge, ...]
    checks: Mapping[str, CheckSpec]


@dataclass(frozen=True)
class ManagedTask:
    task: TaskSpec
    units: tuple[WorkUnit, ...] | None
    edges: tuple[Edge, ...] | None
    checks: Mapping[str, CheckSpec]
    base: str | None


def _task_from_dict(data: Mapping[str, Any]) -> TaskSpec:
    validate("task_spec", data)
    return TaskSpec(
        id=data["id"],
        goal=data["goal"],
        acceptance=tuple(data["acceptance"]),
        risk=RiskRank(data["risk"]),
        mode=data["mode"],
        limits=TaskLimits(**data.get("limits", {})),
        required_capabilities=tuple(data.get("required_capabilities", ())),
    )


def _unit_from_dict(data: Mapping[str, Any]) -> WorkUnit:
    validate("work_unit", data)
    return WorkUnit(
        node_id=data["node_id"],
        kind=NodeKind(data["kind"]),
        depends_on=tuple(data["depends_on"]),
        inputs=dict(data["inputs"]),
        outputs_schema=data["outputs_schema"],
        write_allowlist=tuple(data["write_allowlist"]),
        checks=tuple(data["checks"]),
        risk=RiskRank(data["risk"]),
        prompt=data.get("prompt"),
        host=data.get("host"),
    )


def _edge_from_dict(data: Mapping[str, Any]) -> Edge:
    validate("edge", data)
    return Edge(data["from_node"], data["from_output"], data["to_node"], data["to_input"])


def _checks_from_dict(data: Mapping[str, Any]) -> dict[str, CheckSpec]:
    return {k: CheckSpec(v["tool"], dict(v["args"])) for k, v in data.items()}


def load_task_file(path: Path) -> ManagedTask:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        validate("managed_task", data)
        units = data.get("units")
        edges = data.get("edges")
        return ManagedTask(
            task=_task_from_dict(data["task"]),
            units=None if units is None else tuple(_unit_from_dict(u) for u in units),
            edges=None if units is None else tuple(_edge_from_dict(e) for e in edges or ()),
            checks=_checks_from_dict(data.get("checks", {})),
            base=data.get("base"),
        )
    except (OSError, json.JSONDecodeError, SchemaError) as e:
        raise TaskFileError(f"{path}: {e}") from e


def plan_from_task_file(task_file: Path) -> WorkflowGraph:
    loaded = load_task_file(task_file)
    if loaded.units is None or loaded.edges is None:
        raise TaskFileError(f"{task_file}: units が未指定のため splitter が必要です")
    try:
        return WorkflowGraph.build(loaded.units, loaded.edges)
    except GraphError as e:
        raise TaskFileError(f"{task_file}: invalid graph ({e})") from e


def _plan_schema() -> dict[str, object]:
    # CLI へ渡す契約では units/edges の要素まで具体化し、1 回目から Schema 違反を弾く
    schema = load_schema("split_plan")
    props = cast("dict[str, dict[str, object]]", schema["properties"])
    for key, name in (("units", "work_unit"), ("edges", "edge")):
        item = {k: v for k, v in load_schema(name).items() if k not in ("$schema", "$id")}
        props[key]["items"] = item
    return schema


def _prompt(task: TaskSpec, constraints: Sequence[VerifiedConstraint]) -> str:
    lines = [
        "あなたはタスク分割担当です。ファイルは一切書き換えず、"
        "次のタスクを依存 DAG に分割する計画だけを出力してください。",
        f"目標: {task.goal}",
        "受入条件:",
        *[f"- {a}" for a in task.acceptance],
        "規則: worker は write_allowlist を必ず持ち、checks に決定論的な検証 ID を与える。"
        "worker 群を集約する gate ノードを 1 つ置く。checks の各 ID は tool と args で定義する。",
    ]
    if constraints:
        lines.append("検証済みの制約（必ず守る）:")
        lines += [f"- {c.statement}" for c in constraints]
    return "\n".join(lines)


def _parse_plan(data: Mapping[str, object]) -> tuple[SplitPlan, WorkflowGraph]:
    units = tuple(
        _unit_from_dict(cast("Mapping[str, Any]", u)) for u in cast("list[Any]", data["units"])
    )
    edges = tuple(
        _edge_from_dict(cast("Mapping[str, Any]", e)) for e in cast("list[Any]", data["edges"])
    )
    graph = WorkflowGraph.build(units, edges)
    checks = _checks_from_dict(cast("Mapping[str, Any]", data["checks"]))
    return SplitPlan(units, edges, checks), graph


async def split_with_agent(
    task: TaskSpec,
    runner: CliAgentRunner,
    *,
    root: Path,
    constraints: Sequence[VerifiedConstraint],
    deadline_seconds: int = 600,
) -> SplitPlan:
    schema = _plan_schema()
    context = RunContext(
        worktree=root,
        cwd=root,
        deadline_seconds=deadline_seconds,
        env_allowlist=DEFAULT_ENV_ALLOWLIST,
        permissions_profile="read-only",
    )

    async def run_fn(prompt: str):
        return await runner.run_once(prompt, context)

    prompt = _prompt(task, constraints)
    problem = ""
    # 構造不正は 1 回だけエラー内容を返して再試行する（計 2 回まで）
    for _ in range(2):
        run, result = await run_with_output_contract(
            run_fn, prompt + problem, schema, max_retries=0
        )
        if run.terminal_state in _BLOCKED_TERMINALS:
            raise SplitError(run.terminal_state.value, run.error_code or "", blocked=True)
        if run.terminal_state is not TerminalState.SUCCESS:
            raise SplitError("SPLITTER_FAILED", run.terminal_state.value)
        if not result.ok or result.data is None:
            problem = (
                f"\n\n前回の出力は不正でした（{result.error_code}: {result.message}）。"
                "修正して再出力せよ。"
            )
            continue
        try:
            plan, _ = _parse_plan(result.data)
        except GraphError as e:
            problem = (
                f"\n\n前回の plan のグラフが不正でした: {', '.join(e.codes)}。修正して再出力せよ。"
            )
        except SchemaError as e:
            problem = f"\n\n前回の plan の要素が Schema 違反でした: {e}。修正して再出力せよ。"
        else:
            return plan
    raise SplitError("INVALID_SPLIT", problem.strip())
