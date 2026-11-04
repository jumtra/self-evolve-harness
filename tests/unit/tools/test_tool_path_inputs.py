from pathlib import Path

import pytest

from seh.policy import ALLOW_ALL, Policy
from seh.tools.registry import ToolContext, ToolError, ToolRegistry, ToolSpec


def _registry(calls: list[str]) -> ToolRegistry:
    async def invoke(args, ctx):
        calls.append(str(args["file_path"]))
        return {"ok": True}

    registry = ToolRegistry()
    registry.register(
        ToolSpec(
            name="fs.read",
            description="read",
            input_schema={
                "type": "object",
                "properties": {"file_path": {"type": "string", "x-seh-path": True}},
                "required": ["file_path"],
            },
            output_schema={"type": "object"},
            permissions=frozenset(),
            invoke=invoke,
        )
    )
    return registry


@pytest.mark.parametrize(
    "file_path",
    [
        pytest.param("../../outside.txt", id="PT-01-parent"),
        pytest.param("docs/../../../etc/hosts", id="PT-02-nested"),
        pytest.param("%2e%2e/%2e%2e/outside.txt", id="PT-03-url-encoded"),
        pytest.param("/etc/passwd", id="PT-04-absolute"),
        pytest.param("link_to_outside/file.txt", id="PT-05-symlink"),
    ],
)
async def test_path_escaping_root_is_invalid_input(tmp_path: Path, file_path: str):
    root = tmp_path / "ws"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / "link_to_outside").symlink_to(outside)
    calls: list[str] = []
    ctx = ToolContext(
        root=root, policy=Policy(tool_allowlist=ALLOW_ALL), granted_permissions=frozenset()
    )

    with pytest.raises(ToolError) as exc:
        await _registry(calls).execute("fs.read", {"file_path": file_path}, ctx)

    assert exc.value.code == "INVALID_INPUT"
    assert calls == []


async def test_path_inside_root_is_accepted(tmp_path: Path):
    calls: list[str] = []
    ctx = ToolContext(
        root=tmp_path, policy=Policy(tool_allowlist=ALLOW_ALL), granted_permissions=frozenset()
    )

    result = await _registry(calls).execute("fs.read", {"file_path": "src/ok.py"}, ctx)

    assert result == {"ok": True}
    assert calls == ["src/ok.py"]
