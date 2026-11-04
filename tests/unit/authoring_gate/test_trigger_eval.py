import json
from pathlib import Path

from seh.artifacts import ArtifactStore
from seh.authoring.eval import run_trigger_eval
from seh.contracts import RunContext, RunResult, TerminalState
from seh.runtime.runners.fake import FakeCliRunner


async def test_each_case_runs_in_a_fresh_process_and_is_judged_from_saved_events(
    tmp_path: Path,
) -> None:
    artifacts = ArtifactStore(tmp_path / "artifacts")
    invoked = {
        "type": "assistant",
        "message": {"content": [{"type": "tool_use", "name": "Skill", "input": {"skill": "work"}}]},
    }
    plain = {"type": "assistant", "message": {"content": [{"type": "text", "text": "x"}]}}
    done = {"type": "result"}
    by_prompt = {"バグを直して": [invoked, done], "天気は": [plain, done]}

    def respond(prompt: str, context: RunContext) -> RunResult:
        run_id = "r-pos" if prompt == "バグを直して" else "r-neg"
        text = "\n".join(json.dumps(e) for e in by_prompt[prompt])
        ev = artifacts.put(run_id, "events.jsonl", text)
        return RunResult(
            run_id, "claude", TerminalState.SUCCESS, 0, "ok", None, (ev.uri,), None, None
        )

    runner = FakeCliRunner("claude", respond)
    cases = [
        {
            "id": "PS-TP-01",
            "category": "TRIGGER_POS",
            "target_skill": "work",
            "prompt": "バグを直して",
        },
        {"id": "PS-TN-01", "category": "TRIGGER_NEG", "target_skill": "work", "prompt": "天気は"},
        {"id": "PS-TP-03", "category": "TRIGGER_POS", "target_skill": "other", "prompt": "別"},
        {"id": "PS-OUT-01", "category": "OUTPUT", "target_skill": "work", "prompt": "出力"},
    ]

    run = await run_trigger_eval(
        "work", cases, runner, workdir=tmp_path / "wd", artifacts=artifacts
    )

    assert [(r.case_id, r.category, r.expected_trigger, r.observed) for r in run.results] == [
        ("PS-TP-01", "TRIGGER_POS", True, True),
        ("PS-TN-01", "TRIGGER_NEG", False, False),
    ]
    assert (run.host, run.skill_id) == ("claude", "work")
    assert len(runner.calls) == 2
    assert all(ctx.session_policy == "fresh" for _, ctx in runner.calls)


async def test_failed_run_or_missing_events_is_undetermined_not_false(tmp_path: Path) -> None:
    artifacts = ArtifactStore(tmp_path / "artifacts")
    failed = RunResult("r1", "claude", TerminalState.FAILED, 1, None, None, (), None, "X")
    runner = FakeCliRunner("claude", [failed])
    cases = [{"id": "PS-TN-01", "category": "TRIGGER_NEG", "target_skill": "work", "prompt": "p"}]

    run = await run_trigger_eval(
        "work", cases, runner, workdir=tmp_path / "wd", artifacts=artifacts
    )

    assert [r.observed for r in run.results] == [None]
