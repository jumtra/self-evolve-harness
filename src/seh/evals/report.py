"""EvalRun の集計・比較・保存・Markdown 表示。未計測の数値は推測で埋めない。"""

from __future__ import annotations

import json
import statistics
from collections.abc import Sequence
from dataclasses import asdict, dataclass

from seh.evals.runner import EvalRun, TrialResult

MUST_SPLITS = frozenset({"regression", "holdout"})
UNKNOWN = "UNKNOWN"
UNMEASURED = "未計測"


@dataclass(frozen=True)
class CaseSummary:
    case_id: str
    split: str
    passes: int
    trials: int
    pass_rate: float
    median_tokens: float | None
    median_latency: float
    total_cost: float | None
    retries: int


@dataclass(frozen=True)
class Comparison:
    improved: tuple[str, ...]
    regressed: tuple[str, ...]
    must_regressions: tuple[str, ...]
    promotable: bool


def _trial_tokens(t: TrialResult) -> int | None:
    if t.input_tokens is None or t.output_tokens is None:
        return None
    return t.input_tokens + t.output_tokens


def _median_tokens(trials: Sequence[TrialResult]) -> float | None:
    values = [_trial_tokens(t) for t in trials]
    if not values or any(v is None for v in values):
        return None
    return statistics.median(v for v in values if v is not None)


def _total_cost(trials: Sequence[TrialResult]) -> float | None:
    if not trials or any(t.cost_usd is None for t in trials):
        return None
    return sum(t.cost_usd for t in trials if t.cost_usd is not None)


def summarize(run: EvalRun) -> list[CaseSummary]:
    by_case: dict[str, list[TrialResult]] = {}
    for t in run.trials:
        by_case.setdefault(t.case_id, []).append(t)
    summaries: list[CaseSummary] = []
    for case_id, trials in sorted(by_case.items()):
        passes = sum(1 for t in trials if t.verdict_status == "PASS")
        summaries.append(
            CaseSummary(
                case_id=case_id,
                split=trials[0].split,
                passes=passes,
                trials=len(trials),
                pass_rate=passes / len(trials),
                median_tokens=_median_tokens(trials),
                median_latency=statistics.median(t.latency_seconds for t in trials),
                total_cost=_total_cost(trials),
                retries=sum(t.retries for t in trials),
            )
        )
    return summaries


def compare(baseline: EvalRun, candidate: EvalRun) -> Comparison:
    base = {s.case_id: s for s in summarize(baseline)}
    cand = {s.case_id: s for s in summarize(candidate)}
    improved: list[str] = []
    regressed: list[str] = []
    must: list[str] = []
    for case_id in sorted(base.keys() | cand.keys()):
        before = base.get(case_id)
        after = cand.get(case_id)
        if before is None or after is None:
            # 候補で欠けた must ケースは安全側で後退扱いにする
            if before is not None and before.split in MUST_SPLITS and before.pass_rate > 0:
                regressed.append(case_id)
                must.append(case_id)
            continue
        if after.pass_rate > before.pass_rate:
            improved.append(case_id)
        elif after.pass_rate < before.pass_rate:
            regressed.append(case_id)
            if after.split in MUST_SPLITS:
                must.append(case_id)
    must_all_pass = all(s.pass_rate == 1.0 for s in cand.values() if s.split in MUST_SPLITS)
    return Comparison(
        improved=tuple(improved),
        regressed=tuple(regressed),
        must_regressions=tuple(must),
        promotable=not must and must_all_pass,
    )


def to_json(run: EvalRun) -> str:
    return json.dumps(asdict(run), ensure_ascii=False, indent=2)


def from_json(text: str) -> EvalRun:
    data = json.loads(text)
    trials = tuple(
        TrialResult(**{**t, "evidence_refs": tuple(t["evidence_refs"])}) for t in data["trials"]
    )
    return EvalRun(
        run_id=data["run_id"],
        created_at=data["created_at"],
        variant_id=data["variant_id"],
        components=dict(data["components"]),
        environment=dict(data["environment"]),
        trials=trials,
    )


def _row(run: EvalRun, baseline: EvalRun | None) -> list[str]:
    trials = run.trials
    if not trials:
        return [run.variant_id, *[UNMEASURED] * 6]
    passes = sum(1 for t in trials if t.verdict_status == "PASS")
    tokens = _median_tokens(trials)
    cost = _total_cost(trials)
    if baseline is None:
        regressions, verdict = "-", "比較基準"
    else:
        result = compare(baseline, run)
        regressions = str(len(result.must_regressions))
        verdict = "昇格可" if result.promotable else "昇格不可"
    return [
        run.variant_id,
        f"{passes}/{len(trials)}",
        regressions,
        UNKNOWN if tokens is None else f"{tokens:g}",
        f"{statistics.median(t.latency_seconds for t in trials):.2f}s",
        UNKNOWN if cost is None else f"${cost / len(trials):.4f}",
        verdict,
    ]


def render_markdown(runs: Sequence[EvalRun], comparison: Comparison | None) -> str:
    header = [
        "Variant",
        "Pass/Trials",
        "Critical regressions",
        "Median tokens",
        "Median latency",
        "Cost/run",
        "判定",
    ]
    lines = ["| " + " | ".join(header) + " |", "|" + " --- |" * len(header)]
    for i, run in enumerate(runs):
        baseline = None if i == 0 else runs[0]
        lines.append("| " + " | ".join(_row(run, baseline)) + " |")
    if comparison is not None:
        lines += [
            "",
            f"- improved: {', '.join(comparison.improved) or 'なし'}",
            f"- regressed: {', '.join(comparison.regressed) or 'なし'}",
            f"- must_regressions: {', '.join(comparison.must_regressions) or 'なし'}",
            f"- promotable: {comparison.promotable}",
        ]
    lines += ["", "### 環境"]
    for run in runs:
        env = {**run.components, **{f"env.{k}": v for k, v in run.environment.items()}}
        rendered = ", ".join(f"{k}={UNKNOWN if v is None else v}" for k, v in env.items())
        lines.append(f"- {run.variant_id} ({run.run_id}): {rendered or UNMEASURED}")
    return "\n".join(lines) + "\n"
