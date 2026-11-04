"""git 差分系の決定論的 Tool。argv 実行のみで shell は使わない。"""

from __future__ import annotations

import os
from collections.abc import Mapping
from fnmatch import fnmatchcase

from seh.runtime.process import DEFAULT_ENV_ALLOWLIST, build_env, run_process
from seh.tools.registry import ToolContext, ToolError, ToolSpec

# 先頭 "-" を禁じて base がオプションとして解釈されるのを防ぐ
_BASE_SCHEMA = {"type": "string", "pattern": r"^[A-Za-z0-9._/][A-Za-z0-9._/-]{0,99}$"}
_STRING_LIST = {"type": "array", "items": {"type": "string"}}


async def _git_lines(args: list[str], ctx: ToolContext) -> list[str]:
    result = await run_process(
        ["git", *args],
        cwd=ctx.root,
        env=build_env(DEFAULT_ENV_ALLOWLIST, os.environ),
        timeout_seconds=ctx.timeout_seconds,
    )
    if result.timed_out or result.exit_code != 0:
        stderr = result.stderr.decode(errors="replace")[-500:]
        raise ToolError("TOOL_FAILED", f"git {args[0]} failed: {stderr}")
    return [line for line in result.stdout.decode(errors="replace").splitlines() if line]


async def _diff_names(args: Mapping[str, object], ctx: ToolContext) -> Mapping[str, object]:
    base = str(args["base"])
    changed = await _git_lines(["diff", "--name-only", base, "--"], ctx)
    untracked = await _git_lines(["ls-files", "--others", "--exclude-standard"], ctx)
    return {"changed": changed, "untracked": untracked}


async def _scope_check(args: Mapping[str, object], ctx: ToolContext) -> Mapping[str, object]:
    names = await _diff_names(args, ctx)
    allowlist = [str(g) for g in args["allowlist"]]  # type: ignore[attr-defined]
    touched = [*names["changed"], *names["untracked"]]  # type: ignore[misc]
    outside = sorted({p for p in touched if not any(fnmatchcase(p, g) for g in allowlist)})
    return {"ok": not outside, "outside": outside}


DIFF_NAMES_SPEC = ToolSpec(
    name="git.diff_names",
    description="base からの変更ファイルと未追跡ファイルを列挙する",
    input_schema={
        "type": "object",
        "properties": {"base": _BASE_SCHEMA},
        "required": ["base"],
        "additionalProperties": False,
    },
    output_schema={
        "type": "object",
        "properties": {"changed": _STRING_LIST, "untracked": _STRING_LIST},
        "required": ["changed", "untracked"],
    },
    permissions=frozenset({"read:repository"}),
    invoke=_diff_names,
)

SCOPE_CHECK_SPEC = ToolSpec(
    name="git.scope_check",
    description="変更が allowlist（glob）の範囲内か検査する",
    input_schema={
        "type": "object",
        "properties": {"base": _BASE_SCHEMA, "allowlist": _STRING_LIST},
        "required": ["base", "allowlist"],
        "additionalProperties": False,
    },
    output_schema={
        "type": "object",
        "properties": {"ok": {"type": "boolean"}, "outside": _STRING_LIST},
        "required": ["ok", "outside"],
    },
    permissions=frozenset({"read:repository"}),
    invoke=_scope_check,
)
