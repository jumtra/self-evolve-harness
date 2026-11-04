from pathlib import Path

from seh.contracts import RunContext, RunResult, TerminalState, Usage, VerdictStatus
from seh.evals.fixtures import CheckSpec, EvalCase, TaskSpec
from seh.evals.runner import run_eval
from seh.evals.variants import VARIANTS
from seh.runtime.runners.fake import FakeCliRunner

CORRECT = "CORRECT_VALUE_42"


async def test_correct_fix_passes_with_single_attempt(tmp_path: Path):
    repo = tmp_path / "src_repo"
    repo.mkdir()
    (repo / "answer.txt").write_text("wrong\n")
    case = EvalCase(
        schema_version=1,
        id="E90",
        title="t",
        split="training",
        kind="bugfix",
        task=TaskSpec(goal="answer.txt を直す", acceptance=("answer.txt が正しい",)),
        repo_dir=repo,
        expand_suffix=False,
        checks=(CheckSpec("has", "file_contains", {"path": "answer.txt", "regex": CORRECT}),),
        write_allowlist=("answer.txt",),
        expected_verdict_for_noop=VerdictStatus.FAIL,
        secrets={},
    )

    def fix(prompt: str, context: RunContext) -> RunResult:
        (context.cwd / "answer.txt").write_text(f"{CORRECT}\n")
        return RunResult("r1", "claude", TerminalState.SUCCESS, 0, "done", None, (), None, None)

    runner = FakeCliRunner("claude", fix)

    run = await run_eval([case], VARIANTS["V0"], runner, trials=1, workroot=tmp_path / "work")

    trial = run.trials[0]
    assert (trial.verdict_status, trial.attempts, trial.retries) == ("PASS", 1, 0)
    assert trial.approvals == 0


async def test_noop_agent_fails(tmp_path: Path):
    repo = tmp_path / "src_repo"
    repo.mkdir()
    (repo / "answer.txt").write_text("wrong\n")
    case = EvalCase(
        schema_version=1,
        id="E90",
        title="t",
        split="training",
        kind="bugfix",
        task=TaskSpec(goal="g", acceptance=()),
        repo_dir=repo,
        expand_suffix=False,
        checks=(CheckSpec("has", "file_contains", {"path": "answer.txt", "regex": CORRECT}),),
        write_allowlist=("answer.txt",),
        expected_verdict_for_noop=VerdictStatus.FAIL,
        secrets={},
    )
    runner = FakeCliRunner(
        "claude",
        [RunResult("r1", "claude", TerminalState.SUCCESS, 0, "noop", None, (), None, None)],
    )

    run = await run_eval([case], VARIANTS["V0"], runner, trials=1, workroot=tmp_path / "work")

    assert run.trials[0].verdict_status == "FAIL"
    assert run.trials[0].attempts == 1


async def test_repair_loop_retries_with_failure_feedback(tmp_path: Path):
    repo = tmp_path / "src_repo"
    repo.mkdir()
    (repo / "answer.txt").write_text("wrong\n")
    case = EvalCase(
        schema_version=1,
        id="E90",
        title="t",
        split="training",
        kind="bugfix",
        task=TaskSpec(goal="g", acceptance=()),
        repo_dir=repo,
        expand_suffix=False,
        checks=(
            CheckSpec("has_marker", "file_contains", {"path": "answer.txt", "regex": CORRECT}),
        ),
        write_allowlist=("answer.txt",),
        expected_verdict_for_noop=VerdictStatus.FAIL,
        secrets={},
    )
    calls = 0

    def fix_on_second_call(prompt: str, context: RunContext) -> RunResult:
        nonlocal calls
        calls += 1
        if calls == 2:
            (context.cwd / "answer.txt").write_text(f"{CORRECT}\n")
        return RunResult(
            "r",
            "claude",
            TerminalState.SUCCESS,
            0,
            '{"status": "done", "summary": "s"}',
            None,
            (),
            None,
            None,
        )

    runner = FakeCliRunner("claude", fix_on_second_call)

    run = await run_eval([case], VARIANTS["V5"], runner, trials=1, workroot=tmp_path / "work")

    trial = run.trials[0]
    assert (trial.verdict_status, trial.attempts, trial.retries) == ("PASS", 2, 1)
    assert "has_marker" not in runner.calls[0][0]
    assert "has_marker" in runner.calls[1][0]


async def test_baseline_does_not_repair_after_failure(tmp_path: Path):
    repo = tmp_path / "src_repo"
    repo.mkdir()
    (repo / "answer.txt").write_text("wrong\n")
    case = EvalCase(
        schema_version=1,
        id="E90",
        title="t",
        split="training",
        kind="bugfix",
        task=TaskSpec(goal="g", acceptance=()),
        repo_dir=repo,
        expand_suffix=False,
        checks=(CheckSpec("has", "file_contains", {"path": "answer.txt", "regex": CORRECT}),),
        write_allowlist=("answer.txt",),
        expected_verdict_for_noop=VerdictStatus.FAIL,
        secrets={},
    )
    runner = FakeCliRunner(
        "claude",
        lambda prompt, context: RunResult(
            "r", "claude", TerminalState.SUCCESS, 0, "x", None, (), None, None
        ),
    )

    run = await run_eval([case], VARIANTS["V0"], runner, trials=1, workroot=tmp_path / "work")

    assert len(runner.calls) == 1
    assert run.trials[0].attempts == 1


async def test_missing_usage_is_recorded_as_none_not_zero(tmp_path: Path):
    repo = tmp_path / "src_repo"
    repo.mkdir()
    (repo / "answer.txt").write_text("wrong\n")
    case = EvalCase(
        schema_version=1,
        id="E90",
        title="t",
        split="training",
        kind="bugfix",
        task=TaskSpec(goal="g", acceptance=()),
        repo_dir=repo,
        expand_suffix=False,
        checks=(CheckSpec("has", "file_contains", {"path": "answer.txt", "regex": CORRECT}),),
        write_allowlist=("answer.txt",),
        expected_verdict_for_noop=VerdictStatus.FAIL,
        secrets={},
    )
    runner = FakeCliRunner(
        "claude",
        [RunResult("r", "claude", TerminalState.SUCCESS, 0, "x", None, (), None, None)],
    )

    run = await run_eval([case], VARIANTS["V0"], runner, trials=1, workroot=tmp_path / "work")

    trial = run.trials[0]
    assert (trial.input_tokens, trial.output_tokens, trial.cost_usd) == (None, None, None)


async def test_known_usage_is_summed_across_attempts(tmp_path: Path):
    repo = tmp_path / "src_repo"
    repo.mkdir()
    (repo / "answer.txt").write_text("wrong\n")
    case = EvalCase(
        schema_version=1,
        id="E90",
        title="t",
        split="training",
        kind="bugfix",
        task=TaskSpec(goal="g", acceptance=()),
        repo_dir=repo,
        expand_suffix=False,
        checks=(CheckSpec("has", "file_contains", {"path": "answer.txt", "regex": CORRECT}),),
        write_allowlist=("answer.txt",),
        expected_verdict_for_noop=VerdictStatus.FAIL,
        secrets={},
    )
    usage = Usage(input_tokens=100, output_tokens=10, cost_usd=0.5, raw=None)
    runner = FakeCliRunner(
        "claude",
        lambda prompt, context: RunResult(
            "r",
            "claude",
            TerminalState.SUCCESS,
            0,
            '{"status": "done", "summary": "s"}',
            None,
            (),
            usage,
            None,
        ),
    )

    run = await run_eval([case], VARIANTS["V5"], runner, trials=1, workroot=tmp_path / "work")

    trial = run.trials[0]
    assert trial.attempts == 3
    assert (trial.input_tokens, trial.output_tokens, trial.cost_usd) == (300, 30, 1.5)


async def test_non_success_run_fails_without_repair(tmp_path: Path):
    repo = tmp_path / "src_repo"
    repo.mkdir()
    (repo / "answer.txt").write_text("wrong\n")
    case = EvalCase(
        schema_version=1,
        id="E90",
        title="t",
        split="training",
        kind="bugfix",
        task=TaskSpec(goal="g", acceptance=()),
        repo_dir=repo,
        expand_suffix=False,
        checks=(CheckSpec("has", "file_contains", {"path": "answer.txt", "regex": CORRECT}),),
        write_allowlist=("answer.txt",),
        expected_verdict_for_noop=VerdictStatus.FAIL,
        secrets={},
    )
    runner = FakeCliRunner(
        "claude",
        lambda prompt, context: RunResult(
            "r", "claude", TerminalState.TIMED_OUT, None, None, None, (), None, "DEADLINE"
        ),
    )

    run = await run_eval([case], VARIANTS["V5"], runner, trials=1, workroot=tmp_path / "work")

    trial = run.trials[0]
    assert len(runner.calls) == 1
    assert (trial.verdict_status, trial.attempts, trial.error_code) == ("FAIL", 1, "DEADLINE")


async def test_each_trial_gets_its_own_work_repo(tmp_path: Path):
    repo = tmp_path / "src_repo"
    repo.mkdir()
    (repo / "answer.txt").write_text("wrong\n")
    case = EvalCase(
        schema_version=1,
        id="E90",
        title="t",
        split="training",
        kind="bugfix",
        task=TaskSpec(goal="g", acceptance=()),
        repo_dir=repo,
        expand_suffix=False,
        checks=(CheckSpec("has", "file_contains", {"path": "answer.txt", "regex": CORRECT}),),
        write_allowlist=("answer.txt",),
        expected_verdict_for_noop=VerdictStatus.FAIL,
        secrets={},
    )
    runner = FakeCliRunner(
        "claude",
        lambda prompt, context: RunResult(
            "r", "claude", TerminalState.SUCCESS, 0, "x", None, (), None, None
        ),
    )

    await run_eval([case], VARIANTS["V0"], runner, trials=2, workroot=tmp_path / "work")

    cwds = [context.cwd for _, context in runner.calls]
    assert len(cwds) == 2
    assert cwds[0] != cwds[1]


async def test_prompts_never_contain_check_definitions(tmp_path: Path):
    repo = tmp_path / "src_repo"
    repo.mkdir()
    (repo / "answer.txt").write_text("wrong\n")
    case = EvalCase(
        schema_version=1,
        id="E90",
        title="t",
        split="holdout",
        kind="bugfix",
        task=TaskSpec(goal="answer.txt を直す", acceptance=("正しい値にする",)),
        repo_dir=repo,
        expand_suffix=False,
        checks=(
            CheckSpec("has", "file_contains", {"path": "answer.txt", "regex": CORRECT}),
            CheckSpec("cmd", "command", {"cmd": ["python3", "-c", "print('SECRET_CMD_ZZ')"]}),
        ),
        write_allowlist=("answer.txt",),
        expected_verdict_for_noop=VerdictStatus.FAIL,
        secrets={},
    )
    runner = FakeCliRunner(
        "claude",
        lambda prompt, context: RunResult(
            "r", "claude", TerminalState.SUCCESS, 0, "{}", None, (), None, None
        ),
    )

    for variant in VARIANTS.values():
        await run_eval([case], variant, runner, trials=1, workroot=tmp_path / f"work_{variant.id}")

    assert len(runner.calls) >= 6
    for prompt, _ in runner.calls:
        assert "answer.txt を直す" in prompt
        assert CORRECT not in prompt
        assert "SECRET_CMD_ZZ" not in prompt
        assert "file_contains" not in prompt


async def test_output_contract_marks_invalid_output_as_fail_without_checking(tmp_path: Path):
    repo = tmp_path / "src_repo"
    repo.mkdir()
    (repo / "answer.txt").write_text("wrong\n")
    case = EvalCase(
        schema_version=1,
        id="E90",
        title="t",
        split="training",
        kind="bugfix",
        task=TaskSpec(goal="g", acceptance=()),
        repo_dir=repo,
        expand_suffix=False,
        checks=(CheckSpec("has", "file_contains", {"path": "answer.txt", "regex": CORRECT}),),
        write_allowlist=("answer.txt",),
        expected_verdict_for_noop=VerdictStatus.FAIL,
        secrets={},
    )

    def fix_but_reply_with_prose(prompt: str, context: RunContext) -> RunResult:
        (context.cwd / "answer.txt").write_text(f"{CORRECT}\n")
        return RunResult(
            "r", "claude", TerminalState.SUCCESS, 0, "直しました", None, (), None, None
        )

    runner = FakeCliRunner("claude", fix_but_reply_with_prose)

    run = await run_eval([case], VARIANTS["V2"], runner, trials=1, workroot=tmp_path / "work")

    trial = run.trials[0]
    assert trial.verdict_status == "FAIL"
    assert trial.error_code is not None
    assert trial.error_code.startswith("INVALID_OUTPUT")


async def test_output_contract_accepts_valid_json_and_checks_the_repo(tmp_path: Path):
    repo = tmp_path / "src_repo"
    repo.mkdir()
    (repo / "answer.txt").write_text("wrong\n")
    case = EvalCase(
        schema_version=1,
        id="E90",
        title="t",
        split="training",
        kind="bugfix",
        task=TaskSpec(goal="g", acceptance=()),
        repo_dir=repo,
        expand_suffix=False,
        checks=(CheckSpec("has", "file_contains", {"path": "answer.txt", "regex": CORRECT}),),
        write_allowlist=("answer.txt",),
        expected_verdict_for_noop=VerdictStatus.FAIL,
        secrets={},
    )

    def fix_and_reply_json(prompt: str, context: RunContext) -> RunResult:
        (context.cwd / "answer.txt").write_text(f"{CORRECT}\n")
        reply = '{"status": "done", "summary": "fixed", "changed_files": ["answer.txt"]}'
        return RunResult("r", "claude", TerminalState.SUCCESS, 0, reply, None, (), None, None)

    runner = FakeCliRunner("claude", fix_and_reply_json)

    run = await run_eval([case], VARIANTS["V2"], runner, trials=1, workroot=tmp_path / "work")

    assert run.trials[0].verdict_status == "PASS"
    assert "JSON Schema" in runner.calls[0][0]


async def test_tool_delegation_attaches_initial_test_failure_log(tmp_path: Path):
    repo = tmp_path / "src_repo"
    repo.mkdir()
    (repo / "test_sample.py").write_text("def test_marker_failure():\n    assert False\n")
    case = EvalCase(
        schema_version=1,
        id="E90",
        title="t",
        split="training",
        kind="bugfix",
        task=TaskSpec(goal="g", acceptance=()),
        repo_dir=repo,
        expand_suffix=False,
        checks=(CheckSpec("has", "file_contains", {"path": "test_sample.py", "regex": "zzz"}),),
        write_allowlist=("test_sample.py",),
        expected_verdict_for_noop=VerdictStatus.FAIL,
        secrets={},
    )
    runner = FakeCliRunner(
        "claude",
        lambda prompt, context: RunResult(
            "r", "claude", TerminalState.SUCCESS, 0, "{}", None, (), None, None
        ),
    )

    await run_eval([case], VARIANTS["V3"], runner, trials=1, workroot=tmp_path / "w3")
    await run_eval([case], VARIANTS["V4"], runner, trials=1, workroot=tmp_path / "w4")

    v3_prompt, v4_prompt = runner.calls[0][0], runner.calls[1][0]
    assert "test_marker_failure" not in v3_prompt
    assert "test_marker_failure" in v4_prompt
    assert "情報源の優先順位" in v3_prompt


async def test_components_record_prompt_digest_that_differs_between_variants(tmp_path: Path):
    runner = FakeCliRunner("claude", [])

    run_v0 = await run_eval([], VARIANTS["V0"], runner, trials=1, workroot=tmp_path / "a")
    run_v1 = await run_eval([], VARIANTS["V1"], runner, trials=1, workroot=tmp_path / "b")
    run_v3 = await run_eval([], VARIANTS["V3"], runner, trials=1, workroot=tmp_path / "c")

    assert len(run_v0.components["prompt"]) == 64
    assert (
        len({run_v0.components["prompt"], run_v1.components["prompt"], run_v3.components["prompt"]})
        == 3
    )
    assert run_v0.components["runner"] == "claude"
    assert set(run_v0.components) >= {"prompt", "harness", "checker", "runner"}
    assert run_v0.run_id != run_v1.run_id


async def test_splits_filter_limits_executed_cases(tmp_path: Path):
    repo = tmp_path / "src_repo"
    repo.mkdir()
    (repo / "answer.txt").write_text("wrong\n")
    training = EvalCase(
        schema_version=1,
        id="E90",
        title="t",
        split="training",
        kind="bugfix",
        task=TaskSpec(goal="g", acceptance=()),
        repo_dir=repo,
        expand_suffix=False,
        checks=(CheckSpec("has", "file_contains", {"path": "answer.txt", "regex": CORRECT}),),
        write_allowlist=("answer.txt",),
        expected_verdict_for_noop=VerdictStatus.FAIL,
        secrets={},
    )
    holdout = EvalCase(
        schema_version=1,
        id="E91",
        title="t",
        split="holdout",
        kind="bugfix",
        task=TaskSpec(goal="g", acceptance=()),
        repo_dir=repo,
        expand_suffix=False,
        checks=(CheckSpec("has", "file_contains", {"path": "answer.txt", "regex": CORRECT}),),
        write_allowlist=("answer.txt",),
        expected_verdict_for_noop=VerdictStatus.FAIL,
        secrets={},
    )
    runner = FakeCliRunner(
        "claude",
        lambda prompt, context: RunResult(
            "r", "claude", TerminalState.SUCCESS, 0, "x", None, (), None, None
        ),
    )

    run = await run_eval(
        [training, holdout],
        VARIANTS["V0"],
        runner,
        trials=1,
        workroot=tmp_path / "work",
        splits={"holdout"},
    )

    assert [(t.case_id, t.split) for t in run.trials] == [("E91", "holdout")]
