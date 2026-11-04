from seh.contracts import RunContext, TerminalState
from seh.runtime.runners.base import Invocation
from seh.runtime.runners.codex_cli import CodexCliRunner


async def test_run_once_succeeds_on_real_process_emitting_jsonl(tmp_path):
    script = (
        "import json\n"
        "print(json.dumps({'type':'item.completed','item':{'type':'agent_message','text':'hi'}}))\n"
        "print(json.dumps({'type':'turn.completed','usage':{'input_tokens':3,'output_tokens':1}}))\n"
    )

    class ScriptedCodex(CodexCliRunner):
        def build_invocation(self, prompt: str, context: RunContext) -> Invocation:
            return Invocation(argv=("python3", "-c", script), stdin=prompt.encode())

    context = RunContext(
        worktree=tmp_path, cwd=tmp_path, deadline_seconds=30, env_allowlist=("PATH",)
    )

    result = await ScriptedCodex().run_once("hello", context)

    assert result.terminal_state is TerminalState.SUCCESS
    assert result.final_response == "hi"
    assert result.usage is not None
    assert result.usage.input_tokens == 3
    assert result.usage.cost_usd is None


async def test_run_once_reports_failed_on_turn_failed(tmp_path):
    script = "import json\nprint(json.dumps({'type':'turn.failed','error':{'message':'x'}}))\n"

    class ScriptedCodex(CodexCliRunner):
        def build_invocation(self, prompt: str, context: RunContext) -> Invocation:
            return Invocation(argv=("python3", "-c", script), stdin=prompt.encode())

    context = RunContext(
        worktree=tmp_path, cwd=tmp_path, deadline_seconds=30, env_allowlist=("PATH",)
    )

    result = await ScriptedCodex().run_once("hello", context)

    assert result.terminal_state is TerminalState.FAILED
    assert result.error_code == "TURN_FAILED"
