from pathlib import Path

import pytest

from seh.policy import ALLOW_ALL, Policy
from seh.tools.registry import ToolContext, ToolError, ToolRegistry, ToolSpec, default_registry


def _ctx(
    tmp_path: Path,
    *,
    tools: frozenset[str] = ALLOW_ALL,
    granted: frozenset[str] = frozenset({"read:repository"}),
) -> ToolContext:
    return ToolContext(
        root=tmp_path, policy=Policy(tool_allowlist=tools), granted_permissions=granted
    )


async def test_execute_runs_all_stages_and_returns_output(tmp_path: Path):
    calls: list[int] = []

    async def invoke(args, ctx):
        calls.append(1)
        return {"doubled": args["n"] * 2}

    registry = ToolRegistry()
    registry.register(
        ToolSpec(
            name="math.double",
            description="double",
            input_schema={
                "type": "object",
                "properties": {"n": {"type": "integer"}},
                "required": ["n"],
                "additionalProperties": False,
            },
            output_schema={
                "type": "object",
                "properties": {"doubled": {"type": "integer"}},
                "required": ["doubled"],
            },
            permissions=frozenset({"read:repository"}),
            invoke=invoke,
        )
    )

    result = await registry.execute("math.double", {"n": 21}, _ctx(tmp_path))

    assert result == {"doubled": 42}
    assert calls == [1]


async def test_unknown_tool_is_rejected(tmp_path: Path):
    registry = ToolRegistry()

    with pytest.raises(ToolError) as exc:
        await registry.execute("nope", {}, _ctx(tmp_path))

    assert exc.value.code == "UNKNOWN_TOOL"


async def test_invalid_input_does_not_invoke(tmp_path: Path):
    calls: list[int] = []

    async def invoke(args, ctx):
        calls.append(1)
        return {}

    registry = ToolRegistry()
    registry.register(
        ToolSpec(
            name="t.strict",
            description="d",
            input_schema={
                "type": "object",
                "properties": {"n": {"type": "integer"}},
                "required": ["n"],
                "additionalProperties": False,
            },
            output_schema={"type": "object"},
            permissions=frozenset(),
            invoke=invoke,
        )
    )

    with pytest.raises(ToolError) as exc:
        await registry.execute("t.strict", {"n": "not-int"}, _ctx(tmp_path))

    assert exc.value.code == "INVALID_INPUT"
    assert calls == []


async def test_tool_denied_by_policy_does_not_invoke(tmp_path: Path):
    calls: list[int] = []

    async def invoke(args, ctx):
        calls.append(1)
        return {}

    registry = ToolRegistry()
    registry.register(
        ToolSpec(
            name="t.denied",
            description="d",
            input_schema={"type": "object"},
            output_schema={"type": "object"},
            permissions=frozenset(),
            invoke=invoke,
        )
    )

    with pytest.raises(ToolError) as exc:
        await registry.execute("t.denied", {}, _ctx(tmp_path, tools=frozenset({"other"})))

    assert exc.value.code == "NOT_AUTHORIZED"
    assert calls == []


async def test_missing_permission_does_not_invoke(tmp_path: Path):
    calls: list[int] = []

    async def invoke(args, ctx):
        calls.append(1)
        return {}

    registry = ToolRegistry()
    registry.register(
        ToolSpec(
            name="t.exec",
            description="d",
            input_schema={"type": "object"},
            output_schema={"type": "object"},
            permissions=frozenset({"exec:tests"}),
            invoke=invoke,
        )
    )

    with pytest.raises(ToolError) as exc:
        await registry.execute("t.exec", {}, _ctx(tmp_path, granted=frozenset({"read:repository"})))

    assert exc.value.code == "PERMISSION_NOT_GRANTED"
    assert calls == []


async def test_invoke_exception_becomes_tool_failed_with_masked_message(tmp_path: Path):
    secret = "sk-ant-" + "api03-" + "A" * 30

    async def invoke(args, ctx):
        raise RuntimeError("boom " + secret)

    registry = ToolRegistry()
    registry.register(
        ToolSpec(
            name="t.boom",
            description="d",
            input_schema={"type": "object"},
            output_schema={"type": "object"},
            permissions=frozenset(),
            invoke=invoke,
        )
    )

    with pytest.raises(ToolError) as exc:
        await registry.execute("t.boom", {}, _ctx(tmp_path))

    assert exc.value.code == "TOOL_FAILED"
    assert secret not in exc.value.message


async def test_invalid_output_is_rejected(tmp_path: Path):
    async def invoke(args, ctx):
        return {"doubled": "x"}

    registry = ToolRegistry()
    registry.register(
        ToolSpec(
            name="t.badout",
            description="d",
            input_schema={"type": "object"},
            output_schema={
                "type": "object",
                "properties": {"doubled": {"type": "integer"}},
                "required": ["doubled"],
            },
            permissions=frozenset(),
            invoke=invoke,
        )
    )

    with pytest.raises(ToolError) as exc:
        await registry.execute("t.badout", {}, _ctx(tmp_path))

    assert exc.value.code == "INVALID_OUTPUT"


def test_register_rejects_duplicate_name():
    async def invoke(args, ctx):
        return {}

    spec = ToolSpec(
        name="t.dup",
        description="d",
        input_schema={"type": "object"},
        output_schema={"type": "object"},
        permissions=frozenset(),
        invoke=invoke,
    )
    registry = ToolRegistry()
    registry.register(spec)

    with pytest.raises(ValueError):
        registry.register(spec)


def test_default_registry_registers_standard_tools():
    registry = default_registry()

    assert registry.names() == [
        "git.diff_names",
        "git.scope_check",
        "policy.classify_paths",
        "tests.run",
    ]
    assert registry.get("tests.run").permissions == frozenset({"exec:tests"})
