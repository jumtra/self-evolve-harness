"""許可済みコマンドでテストを実行する Tool。出力は末尾のみ・マスク済みで返す。"""

from __future__ import annotations

import os
from collections.abc import Mapping

from seh.redaction import mask_text
from seh.runtime.process import DEFAULT_ENV_ALLOWLIST, build_env, run_process
from seh.tools.registry import PATH_KEYWORD, ToolContext, ToolError, ToolSpec

_TAIL_CHARS = 4000


def _tail(data: bytes) -> str:
    # マスクを先に行い、切り詰めで秘密値が分断されて検出漏れするのを防ぐ
    return mask_text(data.decode(errors="replace"))[-_TAIL_CHARS:]


async def _run(args: Mapping[str, object], ctx: ToolContext) -> Mapping[str, object]:
    argv = [str(a) for a in args["argv"]]  # type: ignore[attr-defined]
    decision = ctx.policy.authorize_command(argv)
    if not decision.allowed:
        raise ToolError("NOT_AUTHORIZED", decision.message)
    cwd = ctx.root / str(args.get("cwd", "."))
    result = await run_process(
        argv,
        cwd=cwd,
        env=build_env(DEFAULT_ENV_ALLOWLIST, os.environ),
        timeout_seconds=ctx.timeout_seconds,
    )
    return {
        "exit_code": result.exit_code,
        "passed": result.exit_code == 0 and not result.timed_out,
        "stdout_tail": _tail(result.stdout),
        "stderr_tail": _tail(result.stderr),
        "timed_out": result.timed_out,
    }


TESTS_RUN_SPEC = ToolSpec(
    name="tests.run",
    description="許可されたコマンドでテストを実行し結果を返す",
    input_schema={
        "type": "object",
        "properties": {
            "argv": {"type": "array", "items": {"type": "string"}, "minItems": 1},
            "cwd": {"type": "string", PATH_KEYWORD: True},
        },
        "required": ["argv"],
        "additionalProperties": False,
    },
    output_schema={
        "type": "object",
        "properties": {
            "exit_code": {"type": ["integer", "null"]},
            "passed": {"type": "boolean"},
            "stdout_tail": {"type": "string"},
            "stderr_tail": {"type": "string"},
            "timed_out": {"type": "boolean"},
        },
        "required": ["exit_code", "passed", "stdout_tail", "stderr_tail", "timed_out"],
    },
    permissions=frozenset({"exec:tests"}),
    invoke=_run,
)
