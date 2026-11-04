"""同一 fixture・同一 checker で Variant を実行し、試行ごとの結果を記録する。"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import time
import uuid
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import seh
from seh.artifacts import ArtifactStore
from seh.contracts import CliAgentRunner, RunContext, RunResult, TerminalState, Usage
from seh.evals import checker as checker_module
from seh.evals.checker import run_checks
from seh.evals.fixtures import EvalCase, materialize
from seh.evals.variants import (
    OUTPUT_SCHEMA,
    SOURCE_PRIORITY_SECTION,
    Variant,
    load_template,
    prompt_digest,
)
from seh.redaction import mask_text
from seh.runtime.output import output_instructions, validate_output
from seh.runtime.process import DEFAULT_ENV_ALLOWLIST, build_env, run_process

_TEST_LOG_TAIL = 3000
_TEST_LOG_TIMEOUT = 60.0
# 中身の無い見出し（次の見出しか末尾まで空白のみ）を取り除く
_EMPTY_SECTION = re.compile(r"^# [^\n]*\n\s*(?=^# |\Z)", re.MULTILINE)


@dataclass(frozen=True)
class TrialResult:
    case_id: str
    split: str
    trial: int
    verdict_status: str
    attempts: int
    retries: int
    approvals: int
    latency_seconds: float
    input_tokens: int | None
    output_tokens: int | None
    cost_usd: float | None
    error_code: str | None
    evidence_refs: tuple[str, ...]


@dataclass(frozen=True)
class EvalRun:
    run_id: str
    created_at: str
    variant_id: str
    components: Mapping[str, str]
    environment: Mapping[str, str | None]
    trials: tuple[TrialResult, ...]


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _render(template: str, values: Mapping[str, str]) -> str:
    text = template
    for key, value in values.items():
        text = text.replace("{{" + key + "}}", value)
    text = _EMPTY_SECTION.sub("", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip() + "\n"


async def _initial_test_log(work: Path) -> str:
    """tests.run 相当。エージェント実行前のテスト結果を決定論的に取得する。"""
    env = build_env(DEFAULT_ENV_ALLOWLIST, os.environ, {"PYTHONDONTWRITEBYTECODE": "1"})
    try:
        result = await run_process(
            ["python3", "-m", "pytest", "-q", "-p", "no:cacheprovider"],
            cwd=work,
            env=env,
            timeout_seconds=_TEST_LOG_TIMEOUT,
        )
    except OSError as e:
        return f"テストを実行できなかった: {type(e).__name__}"
    output = mask_text(
        result.stdout.decode(errors="replace") + result.stderr.decode(errors="replace")
    )
    return f"exit_code={result.exit_code}\n{output[-_TEST_LOG_TAIL:]}"


def _build_prompt(
    case: EvalCase, variant: Variant, *, test_log: str | None, repair_feedback: str
) -> str:
    # FR-033: 渡すのは goal と acceptance の文章のみ。checks の定義・期待値は含めない
    values = {
        "goal": case.task.goal,
        "acceptance": "\n".join(f"- {a}" for a in case.task.acceptance),
        "output_instructions": output_instructions(OUTPUT_SCHEMA)
        if variant.output_contract
        else "",
        "repair_feedback": repair_feedback,
    }
    prompt = _render(load_template(variant), values)
    if variant.source_priority:
        prompt += f"\n{SOURCE_PRIORITY_SECTION}\n"
    if test_log is not None:
        prompt += f"\n# 初期テスト結果（実行前に取得）\n\n```\n{test_log}\n```\n"
    return prompt


def _sum_known(values: Sequence[int | float | None]) -> int | float | None:
    if not values or any(v is None for v in values):
        return None
    return sum(v for v in values if v is not None)


async def _run_trial(
    case: EvalCase,
    variant: Variant,
    runner: CliAgentRunner,
    trial: int,
    work: Path,
    artifacts: ArtifactStore | None,
    deadline_seconds: int,
) -> TrialResult:
    context = RunContext(
        worktree=work,
        cwd=work,
        deadline_seconds=deadline_seconds,
        env_allowlist=DEFAULT_ENV_ALLOWLIST,
    )
    started = time.monotonic()
    test_log = await _initial_test_log(work) if variant.tool_delegation else None
    usages: list[Usage | None] = []
    evidence: list[str] = []
    feedback = ""
    status, error_code, attempts = "FAIL", None, 0

    while attempts < variant.repair_attempts:
        attempts += 1
        prompt = _build_prompt(case, variant, test_log=test_log, repair_feedback=feedback)
        result: RunResult = await runner.run_once(prompt, context)
        usages.append(result.usage)
        evidence.extend(result.evidence_refs)
        if result.terminal_state != TerminalState.SUCCESS:
            error_code = result.error_code or result.terminal_state.value
            break
        if variant.output_contract:
            checked = validate_output(result, OUTPUT_SCHEMA)
            if not checked.ok:
                error_code = f"INVALID_OUTPUT_{checked.error_code}"
                break
        verdict, _ = await run_checks(case, work, artifacts=artifacts)
        evidence.extend(e.uri for e in verdict.evidence)
        status = verdict.status.value
        if verdict.passed:
            break
        repair = json.dumps(verdict.as_repair_input(), ensure_ascii=False, indent=2)
        feedback = f"前回の検証で失敗した。修正すること。\n```json\n{repair}\n```"

    # usage が欠けた試行が 1 つでもあれば合計は UNKNOWN（0 にしない）
    known = [u for u in usages]
    input_tokens = _sum_known([u.input_tokens if u else None for u in known])
    output_tokens = _sum_known([u.output_tokens if u else None for u in known])
    cost = _sum_known([u.cost_usd if u else None for u in known])
    return TrialResult(
        case_id=case.id,
        split=case.split,
        trial=trial,
        verdict_status=status,
        attempts=attempts,
        retries=attempts - 1,
        approvals=0,
        latency_seconds=time.monotonic() - started,
        input_tokens=int(input_tokens) if input_tokens is not None else None,
        output_tokens=int(output_tokens) if output_tokens is not None else None,
        cost_usd=float(cost) if cost is not None else None,
        error_code=error_code,
        evidence_refs=tuple(dict.fromkeys(evidence)),
    )


def _runner_version(runner: CliAgentRunner) -> str | None:
    try:
        return runner.probe().version
    except Exception:  # probe 失敗は環境情報の欠損であり評価自体は止めない
        return None


async def run_eval(
    cases: Sequence[EvalCase],
    variant: Variant,
    runner: CliAgentRunner,
    *,
    trials: int,
    workroot: Path,
    artifacts: ArtifactStore | None = None,
    splits: Collection[str] | None = None,
    deadline_seconds: int = 600,
) -> EvalRun:
    if trials < 1:
        raise ValueError("trials must be >= 1")
    now = datetime.now(UTC)
    run_id = f"eval-{variant.id}-{now:%Y%m%dT%H%M%SZ}-{uuid.uuid4().hex[:6]}"
    results: list[TrialResult] = []
    for case in cases:
        if splits is not None and case.split not in splits:
            continue
        for trial in range(trials):
            work = materialize(case, workroot / run_id / f"{case.id}-t{trial}")
            results.append(
                await _run_trial(case, variant, runner, trial, work, artifacts, deadline_seconds)
            )
    return EvalRun(
        run_id=run_id,
        created_at=now.isoformat(),
        variant_id=variant.id,
        components={
            "prompt": prompt_digest(variant),
            "harness": seh.__version__,
            "checker": _sha256_file(Path(checker_module.__file__)),
            "runner": runner.host,
        },
        environment={
            "python": platform.python_version(),
            "platform": platform.platform(),
            "runner": runner.host,
            "runner_version": _runner_version(runner),
        },
        trials=tuple(results),
    )
