from __future__ import annotations

import json

import pytest

from seh.contracts.run import RunResult, TerminalState
from seh.contracts.schema import load_schema
from seh.runtime.output import (
    OutputParseError,
    extract_json,
    output_instructions,
    run_with_output_contract,
    validate_output,
)

SCHEMA = {
    "type": "object",
    "properties": {"a": {"type": "string"}, "n": {"type": "integer"}},
    "required": ["a"],
    "additionalProperties": False,
}


def test_extract_json_whole_text():
    assert extract_json('  {"a": "x"}\n') == {"a": "x"}


def test_extract_json_last_json_fence():
    text = 'one\n```json\n{"a": "1"}\n```\ntwo\n```json\n{"a": "2"}\n```\n'
    assert extract_json(text) == {"a": "2"}


def test_extract_json_plain_fence():
    assert extract_json('result:\n```\n{"a": "x"}\n```') == {"a": "x"}


def test_extract_json_invalid_raises_invalid_json():
    with pytest.raises(OutputParseError) as e:
        extract_json("no json here")
    assert e.value.code == "INVALID_JSON"


def test_extract_json_truncated_raises_truncated():
    with pytest.raises(OutputParseError) as e:
        extract_json('{"a": "x", "b": [1, 2')
    assert e.value.code == "TRUNCATED"


def test_validate_output_accepts_bare_json():
    run = RunResult("r", "claude", TerminalState.SUCCESS, 0, '{"a": "x"}', None, (), None, None)
    result = validate_output(run, SCHEMA)
    assert result.ok is True
    assert result.data == {"a": "x"}
    assert result.error_code is None


def test_validate_output_accepts_fenced_json():
    run = RunResult(
        "r",
        "claude",
        TerminalState.SUCCESS,
        0,
        'done\n```json\n{"a": "x"}\n```',
        None,
        (),
        None,
        None,
    )
    assert validate_output(run, SCHEMA).ok is True


def test_validate_output_invalid_json():
    run = RunResult("r", "claude", TerminalState.SUCCESS, 0, "hello", None, (), None, None)
    assert validate_output(run, SCHEMA).error_code == "INVALID_JSON"


def test_validate_output_truncated():
    run = RunResult("r", "claude", TerminalState.SUCCESS, 0, '{"a": "x', None, (), None, None)
    assert validate_output(run, SCHEMA).error_code == "TRUNCATED"


@pytest.mark.parametrize("text", ["", "   "])
def test_validate_output_empty_text(text: str):
    run = RunResult("r", "claude", TerminalState.SUCCESS, 0, text, None, (), None, None)
    assert validate_output(run, SCHEMA).error_code == "EMPTY"


def test_validate_output_none_response_is_empty():
    run = RunResult("r", "claude", TerminalState.SUCCESS, 0, None, None, (), None, None)
    assert validate_output(run, SCHEMA).error_code == "EMPTY"


def test_validate_output_missing_required():
    run = RunResult("r", "claude", TerminalState.SUCCESS, 0, '{"n": 1}', None, (), None, None)
    result = validate_output(run, SCHEMA)
    assert result.ok is False
    assert result.error_code == "SCHEMA_VIOLATION"


def test_validate_output_wrong_type_reports_path():
    run = RunResult(
        "r", "claude", TerminalState.SUCCESS, 0, '{"a": "x", "n": "s"}', None, (), None, None
    )
    result = validate_output(run, SCHEMA)
    assert result.error_code == "SCHEMA_VIOLATION"
    assert "n" in result.message


def test_validate_output_additional_properties():
    run = RunResult(
        "r", "claude", TerminalState.SUCCESS, 0, '{"a": "x", "z": 1}', None, (), None, None
    )
    assert validate_output(run, SCHEMA).error_code == "SCHEMA_VIOLATION"


def test_validate_output_forbidden_field_top_level():
    loose = {"type": "object"}
    run = RunResult(
        "r", "claude", TerminalState.SUCCESS, 0, '{"Reasoning": "..."}', None, (), None, None
    )
    assert validate_output(run, loose).error_code == "FORBIDDEN_FIELD"


def test_validate_output_forbidden_field_nested():
    loose = {"type": "object"}
    text = '{"a": [{"b": {"thinking": "x"}}]}'
    run = RunResult("r", "claude", TerminalState.SUCCESS, 0, text, None, (), None, None)
    assert validate_output(run, loose).error_code == "FORBIDDEN_FIELD"


def test_validate_output_prefers_structured_output():
    run = RunResult(
        "r",
        "claude",
        TerminalState.SUCCESS,
        0,
        "garbage",
        None,
        (),
        None,
        None,
        structured_output={"a": "x"},
    )
    result = validate_output(run, SCHEMA)
    assert result.ok is True
    assert result.data == {"a": "x"}


def test_validate_output_structured_output_still_validated():
    run = RunResult(
        "r",
        "claude",
        TerminalState.SUCCESS,
        0,
        '{"a": "x"}',
        None,
        (),
        None,
        None,
        structured_output={"n": 1},
    )
    assert validate_output(run, SCHEMA).error_code == "SCHEMA_VIOLATION"


def test_validate_output_non_success_run():
    run = RunResult("r", "claude", TerminalState.FAILED, 1, '{"a": "x"}', None, (), None, "E")
    assert validate_output(run, SCHEMA).error_code == "RUN_NOT_SUCCESS"


def test_validate_output_real_final_output_schema_ok():
    schema = load_schema("final_output")
    payload = {
        "task_id": "T1",
        "status": "PASSED",
        "summary": "ok",
        "changed_files": ["a.py"],
        "evidence_refs": ["ev1"],
        "remaining_risks": [],
        "requires_human_approval": False,
    }
    run = RunResult(
        "r", "claude", TerminalState.SUCCESS, 0, json.dumps(payload), None, (), None, None
    )
    assert validate_output(run, schema).ok is True


def test_validate_output_real_final_output_schema_bad_status():
    schema = load_schema("final_output")
    payload = {
        "task_id": "T1",
        "status": "DONE",
        "summary": "ok",
        "changed_files": [],
        "evidence_refs": [],
        "remaining_risks": [],
        "requires_human_approval": False,
    }
    run = RunResult(
        "r", "claude", TerminalState.SUCCESS, 0, json.dumps(payload), None, (), None, None
    )
    assert validate_output(run, schema).error_code == "SCHEMA_VIOLATION"


def test_output_instructions_embeds_schema_and_forbids_thinking():
    text = output_instructions(SCHEMA)
    assert "JSON" in text
    assert "思考過程は出力しない" in text
    assert '"additionalProperties"' in text


async def test_contract_retry_then_ok():
    prompts: list[str] = []
    responses = ["not json", '{"a": "x"}']

    async def run_fn(prompt: str) -> RunResult:
        prompts.append(prompt)
        return RunResult(
            "r",
            "claude",
            TerminalState.SUCCESS,
            0,
            responses[len(prompts) - 1],
            None,
            (),
            None,
            None,
        )

    run, out = await run_with_output_contract(run_fn, "do it", SCHEMA)
    assert out.ok is True
    assert len(prompts) == 2
    assert run.final_response == '{"a": "x"}'
    assert "INVALID_JSON" in prompts[1]
    assert prompts[1].startswith("do it")


async def test_contract_both_invalid_returns_last_invalid():
    calls = 0

    async def run_fn(prompt: str) -> RunResult:
        nonlocal calls
        calls += 1
        return RunResult("r", "claude", TerminalState.SUCCESS, 0, "bad", None, (), None, None)

    _, out = await run_with_output_contract(run_fn, "do it", SCHEMA)
    assert out.ok is False
    assert out.error_code == "INVALID_JSON"
    assert calls == 2


async def test_contract_not_success_is_not_retried():
    calls = 0

    async def run_fn(prompt: str) -> RunResult:
        nonlocal calls
        calls += 1
        return RunResult("r", "claude", TerminalState.TIMED_OUT, None, None, None, (), None, "T")

    _, out = await run_with_output_contract(run_fn, "do it", SCHEMA)
    assert out.error_code == "RUN_NOT_SUCCESS"
    assert calls == 1
