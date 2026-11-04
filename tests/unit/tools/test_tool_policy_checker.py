from pathlib import Path

from seh.policy import ALLOW_ALL, Policy
from seh.tools.registry import ToolContext, default_registry


def _ctx(tmp_path: Path) -> ToolContext:
    return ToolContext(
        root=tmp_path,
        policy=Policy(tool_allowlist=ALLOW_ALL),
        granted_permissions=frozenset({"read:repository"}),
    )


async def test_ordinary_source_is_r0(tmp_path: Path):
    result = await default_registry().execute(
        "policy.classify_paths", {"paths": ["src/app/main.py"]}, _ctx(tmp_path)
    )

    assert result == {"risk": "R0", "protected": []}


async def test_tool_config_is_r1(tmp_path: Path):
    result = await default_registry().execute(
        "policy.classify_paths", {"paths": ["ruff.toml"]}, _ctx(tmp_path)
    )

    assert result["risk"] == "R1"
    assert result["protected"] == []


async def test_protected_path_is_r2_and_listed(tmp_path: Path):
    result = await default_registry().execute(
        "policy.classify_paths",
        {"paths": ["src/app/main.py", ".github/workflows/ci.yml"]},
        _ctx(tmp_path),
    )

    assert result == {"risk": "R2", "protected": [".github/workflows/ci.yml"]}
