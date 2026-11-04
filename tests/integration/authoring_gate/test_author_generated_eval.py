import importlib
import json
from pathlib import Path

import pytest

from seh.artifacts import ArtifactStore
from seh.cli import main
from seh.commands import author as author_cmd
from seh.contracts import (
    ChangeAction,
    GeneratedPlan,
    HostId,
    PlannedChange,
    RenderContext,
    RunContext,
    RunResult,
    TerminalState,
)
from seh.providers.hosts.codex import CodexHostAdapter
from seh.runtime.agent_runner import RunnerRegistry
from seh.runtime.runners.fake import FakeCliRunner
from seh.sync import default_adapters

eval_cmd = importlib.import_module("seh.commands.eval")

CONTRACT = "## Goal\na\n## Inputs\nb\n## Boundaries\nc\n## Output\nd\n## Feedback\ne\n"
OLD = "---\ndescription: 開発依頼で使う\n---\n" + CONTRACT
NEW = OLD + "追記\n"


def test_outcome_eval_gives_runner_generated_skill_from_baseline_then_candidate_spec(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
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
    cases.write_text("[]")
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
    seen: list[str] = []

    def respond(prompt: str, context: RunContext) -> RunResult:
        generated = context.cwd / ".claude" / "skills" / "work" / "SKILL.md"
        seen.append(generated.read_text(encoding="utf-8") if generated.is_file() else "<missing>")
        (context.cwd / "answer.txt").write_text("RIGHT\n")
        return RunResult("o1", "claude", TerminalState.SUCCESS, 0, "done", None, (), None, None)

    registry = RunnerRegistry()
    registry.register(FakeCliRunner("claude", respond))
    monkeypatch.setattr(eval_cmd, "REGISTRY", registry)
    _ = ArtifactStore

    main(["author", "eval", "--root", str(tmp_path), "--record", str(record_file), "--fresh"])

    assert seen, "outcome 評価で runner が一度も呼ばれていない"
    assert "追記" not in seen[0], "baseline 側に候補の内容が混入している"
    assert "追記" in seen[-1], "candidate 側の作業ディレクトリの生成 Skill が候補内容になっていない"


def test_promote_fails_when_generated_artifact_lint_reports_claude_key_leaked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    harness = tmp_path / ".harness"
    (harness / "authoring" / "candidates" / "AUTH-L" / "skills" / "work").mkdir(parents=True)
    (harness / "spec" / "skills" / "work").mkdir(parents=True)
    (harness / "spec" / "instructions").mkdir(parents=True)
    (harness / "config.toml").write_text('profile = "balanced"\n')
    (harness / "spec" / "instructions" / "core.md").write_text("共通方針\n")
    (harness / "spec" / "skills" / "work" / "SKILL.md").write_text(OLD)
    (harness / "authoring" / "candidates" / "AUTH-L" / "skills" / "work" / "SKILL.md").write_text(
        NEW
    )
    skill = tmp_path / ".claude" / "skills" / "work" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("x")
    record_file = harness / "authoring" / "AUTH-L.json"
    record_file.write_text(
        json.dumps(
            {
                "id": "AUTH-L",
                "target_kind": "skill",
                "target_paths": [".harness/spec/skills/work/SKILL.md"],
                "risk": "text_only",
                "exploration": {"evidence_refs": ["file:.claude/skills/work/SKILL.md"]},
                "spec": {
                    "goal": "g",
                    "inputs": "i",
                    "boundaries": "b",
                    "output": "o",
                    "feedback": "f",
                },
                "state": "COMPARED",
            }
        )
    )

    class LeakyCodex(CodexHostAdapter):
        def render(self, spec: object, ctx: RenderContext) -> GeneratedPlan:
            leaked = PlannedChange(
                path=".agents/skills/work/SKILL.md",
                action=ChangeAction.CREATE,
                content=b"---\nname: work\ndescription: d\nallowed-tools: Bash\n---\nbody\n",
                reason="skill",
                owner="host:codex",
            )
            return GeneratedPlan(
                host=HostId.CODEX, changes=(leaked,), diagnostics=(), capabilities=()
            )

    def adapters() -> dict[HostId, object]:
        return {**default_adapters(), HostId.CODEX: LeakyCodex()}

    monkeypatch.setattr(author_cmd, "default_adapters", adapters)

    code = main(["author", "promote", "--root", str(tmp_path), "--record", str(record_file)])

    out = capsys.readouterr().out
    assert code == 1
    assert "gate: FAIL" in out
    assert "LINT_ERROR:CLAUDE_KEY_LEAKED" in out
