from __future__ import annotations

import json
import re
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any, cast

from jsonschema import Draft202012Validator

from seh.contracts.run import RunResult, TerminalState

# FR-027: 非公開思考を出力契約に含めない
FORBIDDEN_KEYS = frozenset({"reasoning", "thinking", "chain_of_thought", "internal_monologue"})

_FENCE = re.compile(r"```(?:json)?[ \t]*\n(.*?)```", re.DOTALL)
_CLOSER = {"{": "}", "[": "]"}


class OutputParseError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class OutputResult:
    ok: bool
    data: Mapping[str, object] | None
    error_code: str | None
    message: str


def extract_json(text: str) -> object:
    stripped = text.strip()
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        pass
    fences = _FENCE.findall(text)
    if fences:
        try:
            return json.loads(fences[-1].strip())
        except json.JSONDecodeError as e:
            raise OutputParseError("INVALID_JSON") from e
    starts = [i for i in (stripped.find("{"), stripped.find("[")) if i >= 0]
    if starts:
        opener = stripped[min(starts)]
        if not stripped.endswith(_CLOSER[opener]):
            raise OutputParseError("TRUNCATED")
    raise OutputParseError("INVALID_JSON")


def _has_forbidden_key(value: object) -> bool:
    if isinstance(value, Mapping):
        items = cast("Mapping[object, object]", value)
        return any(
            (isinstance(k, str) and k.lower() in FORBIDDEN_KEYS) or _has_forbidden_key(v)
            for k, v in items.items()
        )
    if isinstance(value, list):
        return any(_has_forbidden_key(v) for v in cast("list[object]", value))
    return False


def _fail(code: str, message: str) -> OutputResult:
    return OutputResult(ok=False, data=None, error_code=code, message=message)


def validate_output(run: RunResult, schema: Mapping[str, object]) -> OutputResult:
    if run.terminal_state != TerminalState.SUCCESS:
        return _fail("RUN_NOT_SUCCESS", f"terminal_state={run.terminal_state.value}")
    if run.structured_output is not None:
        payload = run.structured_output
    else:
        if run.final_response is None or not run.final_response.strip():
            return _fail("EMPTY", "final response is empty")
        try:
            payload = extract_json(run.final_response)
        except OutputParseError as e:
            return _fail(e.code, f"cannot extract JSON ({e.code})")
    if _has_forbidden_key(payload):
        return _fail("FORBIDDEN_FIELD", "output contains a non-public reasoning field")
    errors = sorted(
        Draft202012Validator(cast("Any", schema)).iter_errors(cast("Any", payload)),
        key=lambda e: list(e.absolute_path),
    )
    if errors:
        first = errors[0]
        path = "/".join(map(str, first.absolute_path)) or "<root>"
        return _fail("SCHEMA_VIOLATION", f"{path}: {first.message}")
    if not isinstance(payload, dict):
        return _fail("SCHEMA_VIOLATION", "<root>: output is not a JSON object")
    return OutputResult(
        ok=True, data=cast("Mapping[str, object]", payload), error_code=None, message=""
    )


def output_instructions(schema: Mapping[str, object]) -> str:
    return (
        "最終応答は次の JSON Schema に従う JSON オブジェクトのみを出力する。"
        "思考過程は出力しない。簡潔な理由と証拠参照だけを含める。\n"
        f"{json.dumps(schema, ensure_ascii=False, indent=2)}"
    )


async def run_with_output_contract(
    run_fn: Callable[[str], Awaitable[RunResult]],
    prompt: str,
    schema: Mapping[str, object],
    *,
    max_retries: int = 1,
) -> tuple[RunResult, OutputResult]:
    base = f"{prompt}\n\n{output_instructions(schema)}"
    current = base
    run = await run_fn(current)
    result = validate_output(run, schema)
    for _ in range(max_retries):
        if result.ok or result.error_code == "RUN_NOT_SUCCESS":
            break
        # FR-097: 継続ではなく新規実行として再試行する
        current = (
            f"{base}\n\n前回の出力は {result.error_code}: {result.message} だった。"
            "Schema に従う JSON のみを再出力せよ。"
        )
        run = await run_fn(current)
        result = validate_output(run, schema)
    return run, result
