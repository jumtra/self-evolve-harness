"""Skill の trigger 評価（fresh session）と、outcome 評価用の Runner 補助。

outcome 評価は seh.evals.runner.run_eval を再利用する（二重実装しない）。
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from seh.artifacts import ArtifactStore
from seh.contracts import (
    CliAgentRunner,
    RunContext,
    RunResult,
    RuntimeCapabilityReport,
    TerminalState,
)
from seh.runtime.process import DEFAULT_ENV_ALLOWLIST

TRIGGER_CATEGORIES = {"TRIGGER_POS": True, "TRIGGER_NEG": False}
_SKILL_NAME_KEYS = ("skill", "command", "name")
_TRIGGER_DEADLINE_SECONDS = 300


@dataclass(frozen=True)
class TriggerResult:
    case_id: str
    category: str
    expected_trigger: bool
    observed: bool | None  # None = 判定不能（推測で True/False にしない）


@dataclass(frozen=True)
class TriggerRun:
    run_id: str
    host: str
    skill_id: str
    results: tuple[TriggerResult, ...]
    created_at: str


def trigger_run_to_json(run: TriggerRun) -> str:
    return json.dumps({"kind": "trigger", **asdict(run)}, ensure_ascii=False, indent=2)


def trigger_run_from_json(text: str) -> TriggerRun:
    data = cast("dict[str, object]", json.loads(text))
    results = tuple(TriggerResult(**r) for r in cast("list[dict[str, object]]", data["results"]))  # pyright: ignore[reportArgumentType]
    return TriggerRun(
        run_id=cast("str", data["run_id"]),
        host=cast("str", data["host"]),
        skill_id=cast("str", data["skill_id"]),
        results=results,
        created_at=cast("str", data["created_at"]),
    )


def _matches(name: object, skill_id: str) -> bool:
    return isinstance(name, str) and (name == skill_id or name.endswith(f":{skill_id}"))


def skill_invoked(host: str, events: Sequence[Mapping[str, object]], skill_id: str) -> bool | None:
    """Claude の stream-json のみ判定する。他ホストは検証手段が無いので None（推測しない）。"""
    if host != "claude":
        return None
    for event in events:
        if event.get("type") != "assistant":
            continue
        message = event.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, list):
            continue
        for block in cast("list[object]", content):
            if not isinstance(block, dict) or block.get("type") != "tool_use":
                continue
            if block.get("name") != "Skill":
                continue
            tool_input = block.get("input")
            if isinstance(tool_input, dict) and any(
                _matches(tool_input.get(key), skill_id) for key in _SKILL_NAME_KEYS
            ):
                return True
    return False if any(e.get("type") == "result" for e in events) else None


def _read_events(result: RunResult, artifacts: ArtifactStore) -> list[Mapping[str, object]] | None:
    uri = next((u for u in result.evidence_refs if u.endswith("/events.jsonl")), None)
    if uri is None:
        return None
    try:
        text = artifacts.resolve(uri).read_text(encoding="utf-8")
        events = [json.loads(line) for line in text.splitlines() if line.strip()]
    except (OSError, ValueError):
        return None
    return [e for e in events if isinstance(e, dict)]


async def run_trigger_eval(
    skill_id: str,
    cases: Sequence[Mapping[str, object]],
    runner: CliAgentRunner,
    *,
    workdir: Path,
    artifacts: ArtifactStore,
    run_id: str | None = None,
) -> TriggerRun:
    workdir.mkdir(parents=True, exist_ok=True)
    now = datetime.now(UTC)
    context = RunContext(
        worktree=workdir,
        cwd=workdir,
        deadline_seconds=_TRIGGER_DEADLINE_SECONDS,
        env_allowlist=DEFAULT_ENV_ALLOWLIST,
        session_policy="fresh",
    )
    results: list[TriggerResult] = []
    for case in cases:
        category = case.get("category")
        if category not in TRIGGER_CATEGORIES or case.get("target_skill") != skill_id:
            continue
        # 各ケースは run_once = 新規プロセス。過去会話を持ち込まない
        run = await runner.run_once(str(case["prompt"]), context)
        events = (
            _read_events(run, artifacts) if run.terminal_state == TerminalState.SUCCESS else None
        )
        observed = None if events is None else skill_invoked(runner.host, events, skill_id)
        results.append(
            TriggerResult(
                str(case["id"]), str(category), TRIGGER_CATEGORIES[str(category)], observed
            )
        )
    return TriggerRun(
        run_id=run_id or f"trigger-{skill_id}-{now:%Y%m%dT%H%M%SZ}-{uuid.uuid4().hex[:6]}",
        host=runner.host,
        skill_id=skill_id,
        results=tuple(results),
        created_at=now.isoformat(),
    )


def _exclude_from_git(workdir: Path, patterns: Sequence[str]) -> None:
    """重ねたファイルを eval の「範囲外変更」判定に混ぜない（git 管理外の作業 repo 前提）。"""
    exclude = workdir / ".git" / "info" / "exclude"
    if not exclude.parent.is_dir():
        return
    known = exclude.read_text(encoding="utf-8").splitlines() if exclude.is_file() else []
    missing = [p for p in patterns if p not in known]
    if missing:
        with exclude.open("a", encoding="utf-8") as f:
            f.write("\n".join(missing) + "\n")


class OverlayRunner:
    """run_once の直前に作業ディレクトリへ files を重ね、baseline / candidate の差を作る。"""

    def __init__(self, inner: CliAgentRunner, files: Mapping[str, bytes]) -> None:
        self._inner = inner
        self._files = files
        self.host = inner.host

    def probe(self) -> RuntimeCapabilityReport:
        return self._inner.probe()

    async def run_once(self, prompt: str, context: RunContext) -> RunResult:
        for rel, data in self._files.items():
            target = context.cwd / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        _exclude_from_git(context.cwd, sorted({rel.split("/")[0] + "/" for rel in self._files}))
        return await self._inner.run_once(prompt, context)

    async def cancel(self, run_id: str) -> None:
        await self._inner.cancel(run_id)
