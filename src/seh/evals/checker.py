"""決定論的 Checker。LLM を使わず exit code / 構造 / 差分スコープで合否を決める。"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import jsonschema

from seh.artifacts import ArtifactStore
from seh.contracts import Evidence, Verdict, VerdictStatus
from seh.evals.fixtures import BASELINE_TAG, CheckSpec, EvalCase, git_env
from seh.globs import match_path, outside_allowlist
from seh.redaction import mask_text
from seh.runtime.process import DEFAULT_ENV_ALLOWLIST, build_env, run_process

WRITE_ALLOWLIST_CHECK_ID = "write_allowlist"
_GIT_TIMEOUT = 30.0


@dataclass(frozen=True)
class CheckResult:
    check_id: str
    passed: bool
    reason_code: str
    evidence: tuple[Evidence, ...]
    detail: str
    # 肯定的検証（command 成功 / file_contains・json_schema 一致）か
    positive: bool = False


@dataclass(frozen=True)
class _Ctx:
    case: EvalCase
    workdir: Path
    artifacts: ArtifactStore | None
    timeout_seconds: float


def _ok(check_id: str, detail: str = "", *, positive: bool = False) -> CheckResult:
    return CheckResult(check_id, True, "PASSED", (), detail, positive)


def _fail(
    check_id: str, reason: str, detail: str = "", evidence: tuple[Evidence, ...] = ()
) -> CheckResult:
    return CheckResult(check_id, False, reason, evidence, detail)


def _str_list(value: Any, label: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise ValueError(f"{label} must be a list of str")
    return value


def _safe_path(workdir: Path, rel: str) -> Path:
    root = workdir.resolve()
    path = (root / rel).resolve()
    if not path.is_relative_to(root):
        raise ValueError(f"path escapes workdir: {rel!r}")
    return path


async def _git_lines(workdir: Path, args: list[str]) -> list[str]:
    result = await run_process(
        ["git", *args], cwd=workdir, env=git_env(), timeout_seconds=_GIT_TIMEOUT
    )
    if result.exit_code != 0 or result.timed_out:
        raise RuntimeError(f"git {args[0]} failed: {result.stderr.decode(errors='replace')[:200]}")
    return [p for p in result.stdout.decode("utf-8", errors="replace").split("\0") if p]


async def _changed_files(workdir: Path) -> list[str]:
    tracked = await _git_lines(workdir, ["diff", "--name-only", "-z", "--no-renames", BASELINE_TAG])
    untracked = await _git_lines(workdir, ["ls-files", "-z", "--others", "--exclude-standard"])
    return sorted(set(tracked) | set(untracked))


async def _check_command(spec: CheckSpec, ctx: _Ctx) -> CheckResult:
    cmd = _str_list(spec.params.get("cmd"), "cmd")
    expect_exit = spec.params.get("expect_exit", 0)
    if not isinstance(expect_exit, int) or isinstance(expect_exit, bool):
        raise ValueError("expect_exit must be int")
    cwd_rel = spec.params.get("cwd", ".")
    if not isinstance(cwd_rel, str):
        raise ValueError("cwd must be str")
    # docs/evals.md は repo ルートを "repo" と書く。作業コピーでは workdir 自身がそれにあたる
    cwd = ctx.workdir if cwd_rel in ("repo", "repo/") else _safe_path(ctx.workdir, cwd_rel)
    regex = spec.params.get("output_regex")
    if regex is not None and not isinstance(regex, str):
        raise ValueError("output_regex must be str")
    compiled = re.compile(regex) if regex is not None else None

    env = build_env(
        DEFAULT_ENV_ALLOWLIST,
        os.environ,
        # 実行副産物でスコープ判定が汚れないようにする
        {"PYTHONDONTWRITEBYTECODE": "1"},
    )
    result = await run_process(cmd, cwd=cwd, env=env, timeout_seconds=ctx.timeout_seconds)
    output = mask_text(
        result.stdout.decode("utf-8", errors="replace")
        + result.stderr.decode("utf-8", errors="replace")
    )
    evidence: tuple[Evidence, ...] = ()
    if ctx.artifacts is not None:
        body = f"exit_code={result.exit_code}\n{output}"
        evidence = (ctx.artifacts.put(ctx.case.id, f"{spec.id}.log", body),)

    tail = output[-500:]
    if result.timed_out:
        return _fail(spec.id, "TIMEOUT", f"timed out after {ctx.timeout_seconds}s", evidence)
    if result.exit_code != expect_exit:
        detail = f"exit {result.exit_code}, expected {expect_exit}\n{tail}"
        return _fail(spec.id, "EXIT_CODE_MISMATCH", detail, evidence)
    if compiled is not None and not compiled.search(output):
        return _fail(spec.id, "OUTPUT_MISMATCH", f"output does not match {regex!r}", evidence)
    return CheckResult(spec.id, True, "PASSED", evidence, f"exit {result.exit_code}", True)


async def _check_diff_scope(spec: CheckSpec, ctx: _Ctx) -> CheckResult:
    return await _scope(spec.id, _str_list(spec.params.get("allow"), "allow"), ctx.workdir)


async def _scope(check_id: str, allow: list[str], workdir: Path) -> CheckResult:
    outside = outside_allowlist(await _changed_files(workdir), allow)
    if outside:
        return _fail(check_id, "OUT_OF_SCOPE_CHANGE", "outside allowlist: " + ", ".join(outside))
    return _ok(check_id)


async def _check_forbidden_change(spec: CheckSpec, ctx: _Ctx) -> CheckResult:
    paths = _str_list(spec.params.get("paths"), "paths")
    hit = [f for f in await _changed_files(ctx.workdir) if any(match_path(f, p) for p in paths)]
    if hit:
        return _fail(spec.id, "FORBIDDEN_CHANGE", "forbidden paths changed: " + ", ".join(hit))
    return _ok(spec.id)


def _read_target(spec: CheckSpec, ctx: _Ctx) -> tuple[Path | None, str]:
    rel = spec.params.get("path")
    if not isinstance(rel, str):
        raise ValueError("path must be str")
    path = _safe_path(ctx.workdir, rel)
    return (path, rel) if path.is_file() else (None, rel)


async def _check_file_contains(spec: CheckSpec, ctx: _Ctx) -> CheckResult:
    regex = spec.params.get("regex")
    if not isinstance(regex, str):
        raise ValueError("regex must be str")
    present = spec.params.get("present", True)
    if not isinstance(present, bool):
        raise ValueError("present must be bool")
    compiled = re.compile(regex)
    path, rel = _read_target(spec, ctx)
    if path is None:
        return _fail(spec.id, "FILE_NOT_FOUND", rel)
    found = compiled.search(path.read_text(encoding="utf-8", errors="replace")) is not None
    if found and not present:
        return _fail(spec.id, "PATTERN_PRESENT", f"{regex!r} found in {rel}")
    if not found and present:
        return _fail(spec.id, "PATTERN_NOT_FOUND", f"{regex!r} not found in {rel}")
    return _ok(spec.id, positive=present)


async def _check_json_schema(spec: CheckSpec, ctx: _Ctx) -> CheckResult:
    schema = spec.params.get("schema")
    if not isinstance(schema, dict):
        raise ValueError("schema must be an object")
    path, rel = _read_target(spec, ctx)
    if path is None:
        return _fail(spec.id, "FILE_NOT_FOUND", rel)
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as e:
        return _fail(spec.id, "INVALID_JSON", f"{rel}: {e}")
    try:
        jsonschema.validate(document, schema)
    except jsonschema.ValidationError as e:
        return _fail(spec.id, "SCHEMA_VIOLATION", e.message[:300])
    return _ok(spec.id, positive=True)


_HANDLERS: dict[str, Callable[[CheckSpec, _Ctx], Awaitable[CheckResult]]] = {
    "command": _check_command,
    "diff_scope": _check_diff_scope,
    "file_contains": _check_file_contains,
    "json_schema": _check_json_schema,
    "forbidden_change": _check_forbidden_change,
}


async def _run_one(spec: CheckSpec, ctx: _Ctx) -> CheckResult:
    handler = _HANDLERS.get(spec.type)
    if handler is None:
        return _fail(spec.id, "UNKNOWN_CHECK", f"unknown check type {spec.type!r}")
    try:
        return await handler(spec, ctx)
    except Exception as e:  # 例外を PASS に化けさせない
        return _fail(spec.id, "CHECKER_ERROR", mask_text(f"{type(e).__name__}: {e}")[:300])


async def run_checks(
    case: EvalCase,
    workdir: Path,
    *,
    artifacts: ArtifactStore | None = None,
    timeout_seconds: float = 120,
) -> tuple[Verdict, tuple[CheckResult, ...]]:
    ctx = _Ctx(case, workdir, artifacts, timeout_seconds)
    results = [await _run_one(spec, ctx) for spec in case.checks]
    # write_allowlist 外の変更は check の定義有無に関わらず FAIL（docs/evals.md の判定規則）
    try:
        results.append(await _scope(WRITE_ALLOWLIST_CHECK_ID, list(case.write_allowlist), workdir))
    except Exception as e:
        detail = mask_text(f"{type(e).__name__}: {e}")[:300]
        results.append(_fail(WRITE_ALLOWLIST_CHECK_ID, "CHECKER_ERROR", detail))

    evidence = tuple(e for r in results for e in r.evidence)
    failed = next((r for r in results if not r.passed), None)
    if failed is not None:
        check_id, reason, status = failed.check_id, failed.reason_code, VerdictStatus.FAIL
    elif not any(r.positive for r in results):
        check_id, reason, status = "aggregate", "NO_POSITIVE_EVIDENCE", VerdictStatus.FAIL
    else:
        check_id, reason, status = "aggregate", "ALL_CHECKS_PASSED", VerdictStatus.PASS
    verdict = Verdict(
        node_id=case.id,
        status=status,
        check_id=check_id,
        reason_code=reason,
        evidence=evidence,
        allowed_repair_scope=case.write_allowlist,
        attempt=1,
        max_attempts=1,
    )
    return verdict, tuple(results)
