"""独立した作業領域、検証、統合を結ぶ managed 実行。"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from seh.artifacts import ArtifactStore
from seh.authoring.lifecycle import write_is_authorized, write_requires_plan
from seh.config import load_config
from seh.contracts import (
    FinalOutput,
    NodeKind,
    RiskRank,
    RunContext,
    Verdict,
    VerdictStatus,
    WorkUnit,
)
from seh.contracts.state import UnitState
from seh.knowledge import load_constraints
from seh.policy import Policy, classify_paths
from seh.runtime.agent_runner import RunnerRegistry
from seh.runtime.checkpoint import CheckpointStore, next_attempt
from seh.runtime.gate import final_gate, final_output_to_dict
from seh.runtime.graph import WorkflowGraph
from seh.runtime.process import DEFAULT_ENV_ALLOWLIST
from seh.runtime.repair import run_unit_with_repair
from seh.runtime.scheduler import Budget, NodeOutcome, Scheduler
from seh.runtime.splitter import SplitError, load_task_file, plan_from_task_file, split_with_agent
from seh.runtime.worktree import UnitWorkspace, WorktreeManager
from seh.tools.registry import ToolContext, ToolError, default_registry
from seh.trace import TraceWriter


@dataclass(frozen=True)
class ManagedOptions:
    host: str
    max_parallel: int
    max_attempts_per_unit: int
    max_seconds_per_unit: int
    max_total_seconds: int
    unattended: bool


async def run_managed(
    root: Path,
    task_file: Path,
    options: ManagedOptions,
    *,
    runners: RunnerRegistry,
    run_id: str | None = None,
    resume: bool = False,
) -> FinalOutput:
    run_id = run_id or uuid.uuid4().hex
    root = root.resolve()
    manager = WorktreeManager(root, run_id=run_id)
    base = await manager.base_commit()
    task = load_task_file(task_file)
    task_digest = hashlib.sha256(task_file.read_bytes()).hexdigest()
    runner = runners.get(options.host)
    run_dir = root / ".harness" / "state" / "runs" / run_id
    store = CheckpointStore(root, run_id)
    checkpoint = store.load() if resume else None
    if resume and checkpoint is None:
        raise ValueError(f"unknown run: {run_id}")
    if checkpoint and checkpoint.task_summary.get("base") != base:
        raise ValueError("BASE_CHANGED: 元のコミットが変更されています")
    if checkpoint and checkpoint.task_summary.get("task_digest") != task_digest:
        raise ValueError("TASK_CHANGED: タスク定義が変更されています")
    artifacts = ArtifactStore(root / ".harness" / "artifacts")
    if task.units is None:
        try:
            if resume:
                plan_path = run_dir / "plan.json"
                task = load_task_file(plan_path)
                graph = plan_from_task_file(plan_path)
                checks = task.checks
            else:
                split_manager = WorktreeManager(root, run_id=f"{run_id}-split")
                split_workspace = await split_manager.create("splitter", base=base)
                try:
                    plan = await split_with_agent(
                        task.task,
                        runner,
                        root=split_workspace.path,
                        constraints=load_constraints(root, now=datetime.now(UTC)),
                    )
                    if await split_manager.changed_paths(split_workspace):
                        raise SplitError("SPLITTER_WROTE_FILES", "splitter modified files")
                finally:
                    await split_manager.cleanup()
                graph = WorkflowGraph.build(plan.units, plan.edges)
                checks = plan.checks
                data = json.loads(task_file.read_text())
                from dataclasses import asdict

                data.update(
                    units=[asdict(u) for u in plan.units],
                    edges=[asdict(e) for e in plan.edges],
                    checks={k: asdict(v) for k, v in checks.items()},
                )
                run_dir.mkdir(parents=True, exist_ok=True)
                (run_dir / "plan.json").write_text(json.dumps(data))
        except SplitError as exc:
            state = UnitState.BLOCKED if exc.blocked else UnitState.FAILED
            return FinalOutput(task.task.id, state, str(exc), (), (), (str(exc),), True)
    else:
        graph = plan_from_task_file(task_file)
        checks = task.checks
    cfg = load_config(root / ".harness" / "config.toml")
    tools = default_registry()
    policy = Policy(
        tool_allowlist=frozenset(tools.names()),
        command_allowlist=frozenset(cfg.runtime.security.command_allowlist),
    )
    workspaces: dict[str, UnitWorkspace] = {}
    evidence: dict[str, tuple[str, ...]] = {}
    if checkpoint:
        for node, outcome in checkpoint.state.outcomes.items():
            refs = outcome.outputs.get("evidence", [])
            if isinstance(refs, list):
                evidence[node] = tuple(str(x) for x in refs)
            if outcome.state is UnitState.PASSED:
                workspaces[node] = UnitWorkspace(node, run_dir / node, f"seh/{run_id}/{node}", base)
    started = time.monotonic()
    previously_spent = checkpoint.budget_spent.get("elapsed_seconds", 0.0) if checkpoint else 0.0

    async def run_node(unit: WorkUnit, deps: object) -> NodeOutcome:
        if unit.kind is NodeKind.GATE:
            units = [
                workspaces[node_id]
                for layer in graph.topological_layers()
                for node_id in layer
                if node_id in workspaces
            ]
            if not units:
                return NodeOutcome(unit.node_id, UnitState.FAILED, "NO_WORKERS")
            result = await manager.integrate(units, target_branch=f"seh/{run_id}/integration")
            if result.conflicts:
                return NodeOutcome(
                    unit.node_id, UnitState.FAILED, f"MERGE_CONFLICT:{result.conflicts[0][0]}"
                )
            changed = sorted({p for n in units for p in changes.get(n.node_id, ())})
            if checkpoint:
                for n in units:
                    if n.node_id not in changes:
                        raw = checkpoint.state.outcomes[n.node_id].outputs.get("changed_files", [])
                        if isinstance(raw, list):
                            changed = sorted(set(changed) | set(raw))
            outputs = {"changed_files": changed, "integration_branch": f"seh/{run_id}/integration"}
            if classify_paths(changed) is RiskRank.R2 or (
                write_requires_plan(root, tuple(changed))
                and not write_is_authorized(root, tuple(changed))
            ):
                return NodeOutcome(
                    unit.node_id,
                    UnitState.WAITING_APPROVAL,
                    "R2_REQUIRES_APPROVAL",
                    outputs=outputs,
                )
            return NodeOutcome(unit.node_id, UnitState.PASSED, None, outputs=outputs)
        if unit.risk is RiskRank.R2 or task.task.risk is RiskRank.R2:
            return NodeOutcome(unit.node_id, UnitState.WAITING_APPROVAL, "R2_REQUIRES_APPROVAL")
        workspace = await manager.create(unit.node_id, base=base)
        dependencies = [workspaces[node] for node in unit.depends_on if node in workspaces]
        if dependencies:
            workspace = await manager.include_dependencies(workspace, dependencies)
        workspaces[unit.node_id] = workspace

        async def check(u: WorkUnit, run: object, cwd: Path) -> Verdict:
            paths = await manager.changed_paths(workspace)
            violations = manager.scope_violations(paths, u.write_allowlist)
            reason = "SCOPE_VIOLATION" if violations else "NO_CHECKS" if not u.checks else "OK"
            details: list[object] = []
            if reason == "OK":
                for check_id in u.checks:
                    spec = checks.get(check_id)
                    if spec is None:
                        reason = "UNKNOWN_CHECK"
                        break
                    try:
                        result = await tools.execute(
                            spec.tool,
                            spec.args,
                            ToolContext(
                                cwd,
                                policy,
                                frozenset({"exec:tests", "read:git"}),
                                options.max_seconds_per_unit,
                            ),
                        )
                    except ToolError as exc:
                        reason = exc.code
                        break
                    details.append(result)
                    if result.get("passed") is not True:
                        reason = "CHECK_FAILED"
                        break
            ev = artifacts.put(
                run_id,
                f"verdict-{u.node_id}.json",
                json.dumps({"reason": reason, "checks": details, "violations": violations}),
            )
            evidence[u.node_id] = (ev.uri,)
            return Verdict(
                u.node_id,
                VerdictStatus.PASS if reason == "OK" else VerdictStatus.FAIL,
                u.checks[0] if u.checks else "checks",
                reason,
                (ev,),
                u.write_allowlist,
                1,
                options.max_attempts_per_unit,
            )

        def compose(u: WorkUnit, feedback: object) -> str:
            return (u.prompt or task.task.goal) + (
                "\n" + json.dumps(feedback, ensure_ascii=False) if feedback else ""
            )

        def context(u: WorkUnit, attempt: int) -> RunContext:
            return RunContext(
                workspace.path,
                workspace.path,
                options.max_seconds_per_unit,
                DEFAULT_ENV_ALLOWLIST,
                permissions_profile="workspace-write",
            )

        old = checkpoint.attempts.get(unit.node_id, ()) if checkpoint else ()
        outcome = await run_unit_with_repair(
            unit,
            runner=runners.get(unit.host or options.host),
            checker=check,
            compose=compose,
            context_for=context,
            max_attempts=options.max_attempts_per_unit,
            start_attempt=next_attempt(old),
            on_attempt=lambda rec: store.append_attempt(unit.node_id, rec),
        )
        if outcome.state is UnitState.PASSED:
            paths = await manager.changed_paths(workspace)
            changes[unit.node_id] = paths
            await manager.commit_unit(workspace, f"seh: {unit.node_id}")
            outcome = NodeOutcome(
                outcome.node_id,
                outcome.state,
                outcome.reason,
                outcome.cost_usd,
                {**outcome.outputs, "changed_files": list(paths)},
            )
        return outcome

    changes: dict[str, tuple[str, ...]] = {}

    def save(state):
        store.save_state(
            state,
            budget_spent={"elapsed_seconds": previously_spent + time.monotonic() - started},
            task_summary={
                "task_file": str(task_file),
                "host": options.host,
                "base": base,
                "task_digest": task_digest,
            },
        )

    scheduler = Scheduler(
        graph,
        run_node,
        Budget(options.max_parallel, max(0.0, options.max_total_seconds - previously_spent)),
        trace=TraceWriter(run_dir / "trace.jsonl"),
        run_id=run_id,
        initial=checkpoint.state if checkpoint else None,
        on_transition=save,
    )
    try:
        state = await scheduler.run()
        save(state)
        result = final_gate(state, graph, evidence, task_id=task.task.id)
        artifacts.put(run_id, "final_output.json", json.dumps(final_output_to_dict(result)))
        return result
    finally:
        await manager.cleanup(keep_branches=True)
