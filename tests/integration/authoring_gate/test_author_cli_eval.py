import importlib
import json
from pathlib import Path

import pytest

from seh.artifacts import ArtifactStore
from seh.cli import main
from seh.contracts import RunContext, RunResult, TerminalState
from seh.runtime.agent_runner import RunnerRegistry
from seh.runtime.runners.fake import FakeCliRunner

eval_cmd = importlib.import_module("seh.commands.eval")

CONTRACT = "## Goal\na\n## Inputs\nb\n## Boundaries\nc\n## Output\nd\n## Feedback\ne\n"
OLD = "---\ndescription: 開発依頼で使う\n---\n" + CONTRACT
NEW = OLD + "追記\n"


def test_eval_then_promote_passes_end_to_end_with_fake_runner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    harness = tmp_path / ".harness"
    (harness / "authoring" / "candidates" / "AUTH-E" / "skills" / "work").mkdir(parents=True)
    (harness / "spec" / "skills" / "work").mkdir(parents=True)
    (harness / "spec" / "instructions").mkdir(parents=True)
    (harness / "config.toml").write_text('profile = "balanced"\n')
    (harness / "spec" / "instructions" / "core.md").write_text("共通方針\n")
    (harness / "spec" / "skills" / "work" / "SKILL.md").write_text(OLD)
    (harness / "authoring" / "candidates" / "AUTH-E" / "skills" / "work" / "SKILL.md").write_text(
        NEW
    )
    skill = tmp_path / ".claude" / "skills" / "work" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("x")
    suite = tmp_path / "tests" / "fixtures" / "eval" / "E01"
    (suite / "repo").mkdir(parents=True)
    (suite / "repo" / "answer.txt").write_text("wrong\n")
    (suite / "case.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "id": "E01",
                "title": "t",
                "split": "regression",
                "kind": "bugfix",
                "task": {"goal": "answer.txt を直す", "acceptance": ["正しい値"]},
                "repo": "repo/",
                "checks": [
                    {"id": "has", "type": "file_contains", "path": "answer.txt", "regex": "RIGHT"}
                ],
                "write_allowlist": ["answer.txt"],
                "expected_verdict_for_noop": "FAIL",
            }
        )
    )
    cases = tmp_path / "tests" / "fixtures" / "prompt_skill" / "cases.json"
    cases.parent.mkdir(parents=True)
    cases.write_text(
        json.dumps(
            [
                {
                    "id": "PS-TP-01",
                    "category": "TRIGGER_POS",
                    "target_skill": "work",
                    "prompt": "バグを直して",
                },
                {
                    "id": "PS-TN-01",
                    "category": "TRIGGER_NEG",
                    "target_skill": "work",
                    "prompt": "天気は",
                },
            ]
        )
    )
    record_file = harness / "authoring" / "AUTH-E.json"
    record_file.write_text(
        json.dumps(
            {
                "id": "AUTH-E",
                "target_kind": "skill",
                "target_paths": [".harness/spec/skills/work/SKILL.md"],
                "risk": "behavioral",
                "exploration": {"evidence_refs": ["file:.claude/skills/work/SKILL.md"]},
                "spec": {
                    "goal": "g",
                    "inputs": "i",
                    "boundaries": "b",
                    "output": "o",
                    "feedback": "f",
                },
                "state": "PLANNED",
            }
        )
    )
    store = ArtifactStore(harness / "artifacts" / "authoring")
    invoked = {
        "type": "assistant",
        "message": {"content": [{"type": "tool_use", "name": "Skill", "input": {"skill": "work"}}]},
    }
    plain = {"type": "assistant", "message": {"content": [{"type": "text", "text": "x"}]}}

    def respond(prompt: str, context: RunContext) -> RunResult:
        if (context.cwd / "answer.txt").exists():
            (context.cwd / "answer.txt").write_text("RIGHT\n")
            return RunResult("o1", "claude", TerminalState.SUCCESS, 0, "done", None, (), None, None)
        events = [invoked if prompt == "バグを直して" else plain, {"type": "result"}]
        evidence = store.put(
            "t-pos" if prompt == "バグを直して" else "t-neg",
            "events.jsonl",
            "\n".join(json.dumps(e) for e in events),
        )
        return RunResult(
            "t1", "claude", TerminalState.SUCCESS, 0, "ok", None, (evidence.uri,), None, None
        )

    registry = RunnerRegistry()
    registry.register(FakeCliRunner("claude", respond))
    monkeypatch.setattr(eval_cmd, "REGISTRY", registry)

    eval_code = main(
        ["author", "eval", "--root", str(tmp_path), "--record", str(record_file), "--fresh"]
    )
    evals = sorted(p.name for p in (harness / "authoring" / "evals").glob("*.json"))
    saved = json.loads(record_file.read_text())
    promote_code = main(
        ["author", "promote", "--root", str(tmp_path), "--record", str(record_file)]
    )

    out = capsys.readouterr().out
    assert eval_code == 0
    assert len(evals) == 3
    assert saved["baseline_run_id"].startswith("eval-V0-")
    assert saved["candidate_run_id"].startswith("eval-V0-")
    assert saved["baseline_run_id"] != saved["candidate_run_id"]
    assert promote_code == 0, out
    assert (harness / "spec" / "skills" / "work" / "SKILL.md").read_text() == NEW


def test_eval_without_registered_runner_records_blocked_and_never_passes_a07(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    harness = tmp_path / ".harness"
    (harness / "authoring").mkdir(parents=True)
    (harness / "config.toml").write_text('profile = "balanced"\n')
    skill = tmp_path / ".claude" / "skills" / "work" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("x")
    record_file = harness / "authoring" / "AUTH-U.json"
    record_file.write_text(
        json.dumps(
            {
                "id": "AUTH-U",
                "target_kind": "skill",
                "target_paths": [".claude/skills/work/SKILL.md"],
                "risk": "behavioral",
                "exploration": {"evidence_refs": ["file:.claude/skills/work/SKILL.md"]},
                "spec": {
                    "goal": "g",
                    "inputs": "i",
                    "boundaries": "b",
                    "output": "o",
                    "feedback": "f",
                },
                "state": "PLANNED",
            }
        )
    )
    monkeypatch.setattr(eval_cmd, "REGISTRY", RunnerRegistry())

    eval_code = main(
        [
            "author",
            "eval",
            "--root",
            str(tmp_path),
            "--record",
            str(record_file),
            "--hosts",
            "claude",
        ]
    )
    promote_code = main(
        ["author", "promote", "--root", str(tmp_path), "--record", str(record_file)]
    )

    out = capsys.readouterr().out
    assert eval_code == 0
    assert "BLOCKED_NO_EVAL claude: RUNNER_NOT_REGISTERED: claude" in out
    assert promote_code == 1
    assert "gate: BLOCKED_NO_EVAL" in out
    assert "NO_FRESH_EVAL:claude" in out


def test_antigravity_is_blocked_even_when_a_runner_is_registered(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    harness = tmp_path / ".harness"
    (harness / "authoring").mkdir(parents=True)
    (harness / "config.toml").write_text('profile = "balanced"\n')
    skill = tmp_path / ".claude" / "skills" / "work" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("x")
    record_file = harness / "authoring" / "AUTH-G.json"
    record_file.write_text(
        json.dumps(
            {
                "id": "AUTH-G",
                "target_kind": "skill",
                "target_paths": [".claude/skills/work/SKILL.md"],
                "risk": "behavioral",
                "exploration": {"evidence_refs": ["file:.claude/skills/work/SKILL.md"]},
                "spec": {"goal": "g"},
                "state": "PLANNED",
            }
        )
    )
    registry = RunnerRegistry()
    registry.register(
        FakeCliRunner(
            "antigravity",
            lambda p, c: RunResult(
                "r", "antigravity", TerminalState.SUCCESS, 0, "", None, (), None, None
            ),
        )
    )
    monkeypatch.setattr(eval_cmd, "REGISTRY", registry)

    code = main(
        [
            "author",
            "eval",
            "--root",
            str(tmp_path),
            "--record",
            str(record_file),
            "--hosts",
            "antigravity",
        ]
    )

    saved = [
        json.loads(p.read_text()) for p in (harness / "authoring" / "evals").glob("trigger-*.json")
    ]
    assert code == 0
    assert "BLOCKED_NO_EVAL antigravity: POLICY_BLOCKED" in capsys.readouterr().out
    assert [r["observed"] for r in saved[0]["results"]] == [None]
