import importlib
import json
from pathlib import Path

import pytest

from seh.cli import main
from seh.contracts import RunContext, RunResult, TerminalState
from seh.runtime.agent_runner import RunnerRegistry
from seh.runtime.runners.fake import FakeCliRunner

eval_cmd = importlib.import_module("seh.commands.eval")


def _write_suite(root: Path) -> Path:
    case_dir = root / "suite" / "E01"
    (case_dir / "repo").mkdir(parents=True)
    (case_dir / "repo" / "answer.txt").write_text("wrong\n")
    (case_dir / "case.json").write_text(
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
    return root / "suite"


def test_run_saves_result_json_with_fake_runner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    suite = _write_suite(tmp_path)

    def fix(prompt: str, context: RunContext) -> RunResult:
        (context.cwd / "answer.txt").write_text("RIGHT\n")
        return RunResult("r", "claude", TerminalState.SUCCESS, 0, "ok", None, (), None, None)

    registry = RunnerRegistry()
    registry.register(FakeCliRunner("claude", fix))
    monkeypatch.setattr(eval_cmd, "REGISTRY", registry)
    out = tmp_path / "result.json"

    code = main(
        ["eval", "run", "--root", str(tmp_path), "--suite", str(suite), "--variant", "V0",
         "--trials", "2", "--host", "claude", "--out", str(out)]
    )  # fmt: skip

    saved = json.loads(out.read_text())
    assert code == 0
    assert saved["variant_id"] == "V0"
    assert [t["verdict_status"] for t in saved["trials"]] == ["PASS", "PASS"]
    assert "2/2" in capsys.readouterr().out


def test_run_with_unregistered_host_exits_1(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    suite = _write_suite(tmp_path)
    monkeypatch.setattr(eval_cmd, "REGISTRY", RunnerRegistry())

    code = main(
        ["eval", "run", "--root", str(tmp_path), "--suite", str(suite), "--variant", "V0",
         "--host", "codex"]
    )  # fmt: skip

    assert code == 1
    assert "codex の Runner は未実装です" in capsys.readouterr().err


def test_run_with_antigravity_is_policy_blocked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    suite = _write_suite(tmp_path)
    registry = RunnerRegistry()
    registry.register(
        FakeCliRunner(
            "antigravity",
            [RunResult("r", "antigravity", TerminalState.SUCCESS, 0, "x", None, (), None, None)],
        )
    )
    monkeypatch.setattr(eval_cmd, "REGISTRY", registry)

    code = main(
        ["eval", "run", "--root", str(tmp_path), "--suite", str(suite), "--variant", "V0",
         "--host", "antigravity"]
    )  # fmt: skip

    assert code == 1
    assert "POLICY_BLOCKED" in capsys.readouterr().err


def _write_run(path: Path, rate_status: str) -> None:
    path.write_text(
        json.dumps(
            {
                "run_id": "eval-x",
                "created_at": "2026-01-01T00:00:00+00:00",
                "variant_id": "V0",
                "components": {},
                "environment": {},
                "trials": [
                    {
                        "case_id": "E01",
                        "split": "regression",
                        "trial": 0,
                        "verdict_status": rate_status,
                        "attempts": 1,
                        "retries": 0,
                        "approvals": 0,
                        "latency_seconds": 1.0,
                        "input_tokens": None,
                        "output_tokens": None,
                        "cost_usd": None,
                        "error_code": None,
                        "evidence_refs": [],
                    }
                ],
            }
        )
    )


def test_compare_exits_0_when_promotable(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    _write_run(tmp_path / "base.json", "PASS")
    _write_run(tmp_path / "cand.json", "PASS")

    code = main(["eval", "compare", str(tmp_path / "base.json"), str(tmp_path / "cand.json")])

    assert code == 0
    assert "promotable" in capsys.readouterr().out


def test_compare_exits_1_when_not_promotable_in_json_format(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    _write_run(tmp_path / "base.json", "PASS")
    _write_run(tmp_path / "cand.json", "FAIL")

    code = main(
        ["eval", "compare", str(tmp_path / "base.json"), str(tmp_path / "cand.json"),
         "--format", "json"]
    )  # fmt: skip

    payload = json.loads(capsys.readouterr().out)
    assert code == 1
    assert payload["promotable"] is False
    assert payload["must_regressions"] == ["E01"]
