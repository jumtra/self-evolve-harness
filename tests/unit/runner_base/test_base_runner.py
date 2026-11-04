import asyncio
import json
import sys
from pathlib import Path

import pytest

from seh.artifacts import ArtifactStore
from seh.contracts import RunContext, TerminalState
from seh.runtime.runners.fake import ScriptedVendorRunner

_OK_SCRIPT = (
    "import json;"
    "print(json.dumps({'type':'result','ok':True,'text':'done',"
    "'usage':{'input_tokens':3,'output_tokens':4,'cost_usd':0.5}}))"
)


def _context(tmp_path: Path, deadline: int = 20) -> RunContext:
    return RunContext(tmp_path, tmp_path, deadline, ("PATH",))


async def test_success_result_carries_response_usage_and_digest(tmp_path):
    runner = ScriptedVendorRunner(_OK_SCRIPT)

    result = await runner.run_once("hi", _context(tmp_path))

    assert result.terminal_state is TerminalState.SUCCESS
    assert result.final_response == "done"
    assert result.exit_code == 0
    assert result.usage is not None
    assert (result.usage.input_tokens, result.usage.output_tokens, result.usage.cost_usd) == (
        3,
        4,
        0.5,
    )
    assert result.event_log_digest is not None
    assert result.host == runner.host


async def test_exit_zero_without_terminal_event_is_invalid_output(tmp_path):
    runner = ScriptedVendorRunner('print(\'{"type":"progress"}\')')

    result = await runner.run_once("hi", _context(tmp_path))

    assert result.exit_code == 0
    assert result.terminal_state is TerminalState.INVALID_OUTPUT


async def test_malformed_json_line_is_invalid_output(tmp_path):
    runner = ScriptedVendorRunner("print('not json')")

    result = await runner.run_once("hi", _context(tmp_path))

    assert result.terminal_state is TerminalState.INVALID_OUTPUT


async def test_permission_denials_downgrade_success_to_failed(tmp_path):
    script = (
        "import json;"
        "print(json.dumps({'type':'result','ok':True,'text':'x',"
        "'permission_denials':[{'tool':'Bash'}]}))"
    )
    runner = ScriptedVendorRunner(script)

    result = await runner.run_once("hi", _context(tmp_path))

    assert result.exit_code == 0
    assert result.terminal_state is TerminalState.FAILED
    assert result.error_code == "PERMISSION_DENIED"
    assert result.permission_denials == ({"tool": "Bash"},)


async def test_timeout_maps_to_timed_out(tmp_path):
    runner = ScriptedVendorRunner("import time; time.sleep(30)")

    result = await runner.run_once("hi", _context(tmp_path, deadline=1))

    assert result.terminal_state is TerminalState.TIMED_OUT


async def test_missing_command_maps_to_unsupported(tmp_path):
    runner = ScriptedVendorRunner(_OK_SCRIPT, command="seh-no-such-command-xyz")

    result = await runner.run_once("hi", _context(tmp_path))

    assert result.terminal_state is TerminalState.UNSUPPORTED
    assert result.error_code == "CLI_NOT_FOUND"


async def test_cancel_by_run_id_maps_to_cancelled(tmp_path):
    runner = ScriptedVendorRunner("import time; time.sleep(30)")
    task = asyncio.create_task(runner.run_once("hi", _context(tmp_path)))
    for _ in range(200):
        if runner.active_run_ids():
            break
        await asyncio.sleep(0.05)
    (run_id,) = runner.active_run_ids()

    await runner.cancel(run_id)
    result = await task

    assert result.terminal_state is TerminalState.CANCELLED
    assert runner.active_run_ids() == ()


async def test_cancel_unknown_run_id_does_nothing(tmp_path):
    runner = ScriptedVendorRunner(_OK_SCRIPT)

    await runner.cancel("unknown")


async def test_task_cancellation_propagates_cancelled_error(tmp_path):
    runner = ScriptedVendorRunner("import time; time.sleep(30)")
    task = asyncio.create_task(runner.run_once("hi", _context(tmp_path)))
    for _ in range(200):
        if runner.active_run_ids():
            break
        await asyncio.sleep(0.05)

    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task
    assert runner.active_run_ids() == ()


async def test_missing_usage_is_none_not_zero(tmp_path):
    script = "import json; print(json.dumps({'type':'result','ok':True,'text':'x'}))"
    runner = ScriptedVendorRunner(script)

    result = await runner.run_once("hi", _context(tmp_path))

    assert result.terminal_state is TerminalState.SUCCESS
    assert result.usage is None


async def test_claudecode_env_is_not_passed_to_child(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDECODE", "1")
    script = (
        "import json, os;"
        "print(json.dumps({'type':'result','ok':True,"
        "'text':json.dumps(sorted(os.environ))}))"
    )
    runner = ScriptedVendorRunner(script)
    context = RunContext(tmp_path, tmp_path, 20, ("PATH", "CLAUDECODE"))

    result = await runner.run_once("hi", context)

    assert result.final_response is not None
    child_env_keys = json.loads(result.final_response)
    assert "CLAUDECODE" not in child_env_keys
    assert "PATH" in child_env_keys


async def test_prompt_is_delivered_via_stdin(tmp_path):
    script = (
        "import json, sys;print(json.dumps({'type':'result','ok':True,'text':sys.stdin.read()}))"
    )
    runner = ScriptedVendorRunner(script)

    result = await runner.run_once("hello prompt", _context(tmp_path))

    assert result.final_response == "hello prompt"


async def test_artifacts_are_saved_with_secrets_masked(tmp_path):
    secret = "sk-ant-" + "a" * 40
    script = (
        "import json, sys;"
        f"print(json.dumps({{'type':'result','ok':True,'text':'{secret}'}}));"
        f"sys.stderr.write('err {secret}')"
    )
    store = ArtifactStore(tmp_path / "artifacts")
    runner = ScriptedVendorRunner(script, artifacts=store)

    result = await runner.run_once("hi", _context(tmp_path))

    assert len(result.evidence_refs) == 2
    saved = [store.resolve(uri).read_text() for uri in result.evidence_refs]
    assert any("type" in text for text in saved)
    assert all(secret not in text for text in saved)
    names = sorted(store.resolve(uri).name for uri in result.evidence_refs)
    assert names == ["events.jsonl", "stderr.txt"]


async def test_no_evidence_refs_without_artifact_store(tmp_path):
    runner = ScriptedVendorRunner(_OK_SCRIPT)

    result = await runner.run_once("hi", _context(tmp_path))

    assert result.evidence_refs == ()


def test_probe_uses_probe_spec_of_subclass():
    runner = ScriptedVendorRunner(_OK_SCRIPT, command=sys.executable)

    report = runner.probe()

    assert report.host == runner.host
    assert report.installed is True
