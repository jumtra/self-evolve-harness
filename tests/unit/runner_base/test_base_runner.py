import asyncio
import json
import sys

import pytest

from seh.artifacts import ArtifactStore
from seh.contracts import RunContext, TerminalState
from seh.runtime.runners.fake import ScriptedVendorRunner


async def test_success_result_carries_response_usage_and_digest(tmp_path):
    script = (
        "import json;"
        "print(json.dumps({'type':'result','ok':True,'text':'done',"
        "'usage':{'input_tokens':3,'output_tokens':4,'cost_usd':0.5}}))"
    )
    runner = ScriptedVendorRunner(script)

    result = await runner.run_once("hi", RunContext(tmp_path, tmp_path, 20, ("PATH",)))

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

    result = await runner.run_once("hi", RunContext(tmp_path, tmp_path, 20, ("PATH",)))

    assert result.exit_code == 0
    assert result.terminal_state is TerminalState.INVALID_OUTPUT


async def test_malformed_json_line_is_invalid_output(tmp_path):
    runner = ScriptedVendorRunner("print('not json')")

    result = await runner.run_once("hi", RunContext(tmp_path, tmp_path, 20, ("PATH",)))

    assert result.terminal_state is TerminalState.INVALID_OUTPUT


async def test_permission_denials_downgrade_success_to_failed(tmp_path):
    script = (
        "import json;"
        "print(json.dumps({'type':'result','ok':True,'text':'x',"
        "'permission_denials':[{'tool':'Bash'}]}))"
    )
    runner = ScriptedVendorRunner(script)

    result = await runner.run_once("hi", RunContext(tmp_path, tmp_path, 20, ("PATH",)))

    assert result.exit_code == 0
    assert result.terminal_state is TerminalState.FAILED
    assert result.error_code == "PERMISSION_DENIED"
    assert result.permission_denials == ({"tool": "Bash"},)


async def test_timeout_maps_to_timed_out(tmp_path):
    runner = ScriptedVendorRunner("import time; time.sleep(30)")

    result = await runner.run_once("hi", RunContext(tmp_path, tmp_path, 1, ("PATH",)))

    assert result.terminal_state is TerminalState.TIMED_OUT


async def test_missing_command_maps_to_unsupported(tmp_path):
    runner = ScriptedVendorRunner("print(1)", command="seh-no-such-command-xyz")

    result = await runner.run_once("hi", RunContext(tmp_path, tmp_path, 20, ("PATH",)))

    assert result.terminal_state is TerminalState.UNSUPPORTED
    assert result.error_code == "CLI_NOT_FOUND"


async def test_cancel_by_run_id_maps_to_cancelled(tmp_path):
    runner = ScriptedVendorRunner("import time; time.sleep(30)")
    task = asyncio.create_task(runner.run_once("hi", RunContext(tmp_path, tmp_path, 20, ("PATH",))))
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
    runner = ScriptedVendorRunner(
        "import json; print(json.dumps({'type':'result','ok':True,'text':'done'}))"
    )

    await runner.cancel("unknown")


async def test_task_cancellation_propagates_cancelled_error(tmp_path):
    runner = ScriptedVendorRunner("import time; time.sleep(30)")
    task = asyncio.create_task(runner.run_once("hi", RunContext(tmp_path, tmp_path, 20, ("PATH",))))
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

    result = await runner.run_once("hi", RunContext(tmp_path, tmp_path, 20, ("PATH",)))

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

    result = await runner.run_once("hello prompt", RunContext(tmp_path, tmp_path, 20, ("PATH",)))

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

    result = await runner.run_once("hi", RunContext(tmp_path, tmp_path, 20, ("PATH",)))

    assert len(result.evidence_refs) == 2
    events_ref, stderr_ref = result.evidence_refs
    events_text = store.resolve(events_ref).read_text()
    stderr_text = store.resolve(stderr_ref).read_text()
    assert store.resolve(events_ref).name == "events.jsonl"
    assert store.resolve(stderr_ref).name == "stderr.txt"
    assert '"type"' in events_text
    assert secret not in events_text
    assert secret not in stderr_text


async def test_no_evidence_refs_without_artifact_store(tmp_path):
    runner = ScriptedVendorRunner(
        "import json; print(json.dumps({'type':'result','ok':True,'text':'done'}))"
    )

    result = await runner.run_once("hi", RunContext(tmp_path, tmp_path, 20, ("PATH",)))

    assert result.evidence_refs == ()


def test_probe_uses_probe_spec_of_subclass():
    runner = ScriptedVendorRunner(
        "import json; print(json.dumps({'type':'result','ok':True}))", command=sys.executable
    )

    report = runner.probe()

    assert report.host == runner.host
    assert report.installed is True


async def test_vendor_reports_not_ok_with_nonzero_exit_is_failed_vendor_error(tmp_path):
    script = (
        "import json, sys;print(json.dumps({'type':'result','ok':False,'text':'boom'}));sys.exit(2)"
    )
    runner = ScriptedVendorRunner(script)

    result = await runner.run_once("hi", RunContext(tmp_path, tmp_path, 20, ("PATH",)))

    assert result.exit_code == 2
    assert result.terminal_state is TerminalState.FAILED
    assert result.error_code == "VENDOR_ERROR"


async def test_ok_true_with_exit_one_is_failed_nonzero_exit(tmp_path):
    script = (
        "import json, sys;print(json.dumps({'type':'result','ok':True,'text':'done'}));sys.exit(1)"
    )
    runner = ScriptedVendorRunner(script)

    result = await runner.run_once("hi", RunContext(tmp_path, tmp_path, 20, ("PATH",)))

    assert result.exit_code == 1
    assert result.terminal_state is TerminalState.FAILED
    assert result.error_code == "NONZERO_EXIT"


async def test_truncated_stdout_is_invalid_output(tmp_path):
    runner = ScriptedVendorRunner("print('x' * 11_000_000)")

    result = await runner.run_once("hi", RunContext(tmp_path, tmp_path, 60, ("PATH",)))

    assert result.terminal_state is TerminalState.INVALID_OUTPUT
    assert result.error_code == "OUTPUT_TRUNCATED"


async def test_missing_cwd_is_invalid_context(tmp_path):
    runner = ScriptedVendorRunner("print(1)")
    missing = tmp_path / "does-not-exist"

    result = await runner.run_once("hi", RunContext(tmp_path, missing, 20, ("PATH",)))

    assert result.terminal_state is TerminalState.FAILED
    assert result.error_code == "INVALID_CONTEXT"
    assert result.exit_code is None


async def test_non_positive_deadline_is_invalid_context(tmp_path):
    runner = ScriptedVendorRunner("print(1)")

    result = await runner.run_once("hi", RunContext(tmp_path, tmp_path, 0, ("PATH",)))

    assert result.terminal_state is TerminalState.FAILED
    assert result.error_code == "INVALID_CONTEXT"


async def test_non_executable_command_is_unsupported_cli_not_executable(tmp_path):
    script_file = tmp_path / "not-executable"
    script_file.write_text("#!/bin/sh\n")
    script_file.chmod(0o644)
    runner = ScriptedVendorRunner("print(1)", command=str(script_file))

    result = await runner.run_once("hi", RunContext(tmp_path, tmp_path, 20, ("PATH",)))

    assert result.terminal_state is TerminalState.UNSUPPORTED
    assert result.error_code == "CLI_NOT_EXECUTABLE"


async def test_final_response_and_structured_output_are_masked(tmp_path):
    secret = "sk-ant-" + "a" * 40
    script = f"import json;print(json.dumps({{'type':'result','ok':True,'text':'key {secret}'}}))"
    runner = ScriptedVendorRunner(script)

    result = await runner.run_once("hi", RunContext(tmp_path, tmp_path, 20, ("PATH",)))

    assert result.final_response is not None
    assert secret not in result.final_response
    assert "[REDACTED]" in result.final_response


async def test_permission_denials_are_masked(tmp_path):
    secret = "sk-ant-" + "b" * 40
    script = (
        "import json;"
        "print(json.dumps({'type':'result','ok':True,'text':'x',"
        f"'permission_denials':[{{'tool':'Bash','cmd':'run {secret}'}}]}}))"
    )
    runner = ScriptedVendorRunner(script)

    result = await runner.run_once("hi", RunContext(tmp_path, tmp_path, 20, ("PATH",)))

    assert result.permission_denials == ({"tool": "Bash", "cmd": "run [REDACTED]"},)
