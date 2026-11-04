"""パス集合のリスク分類（policy.py の判定をそのまま公開する決定論的 Tool）。"""

from __future__ import annotations

from collections.abc import Mapping

from seh.policy import classify_paths, is_protected_path
from seh.tools.registry import PATH_KEYWORD, ToolContext, ToolError, ToolSpec


def _str_list(value: object) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise ToolError("INVALID_INPUT", "expected a list of strings")
    return list(value)


async def _classify(args: Mapping[str, object], ctx: ToolContext) -> Mapping[str, object]:
    paths = _str_list(args["paths"])
    return {
        "risk": str(classify_paths(paths)),
        "protected": [p for p in paths if is_protected_path(p)],
    }


CLASSIFY_PATHS_SPEC = ToolSpec(
    name="policy.classify_paths",
    description="パス集合のリスクランクと保護対象パスを返す",
    input_schema={
        "type": "object",
        "properties": {"paths": {"type": "array", "items": {"type": "string", PATH_KEYWORD: True}}},
        "required": ["paths"],
        "additionalProperties": False,
    },
    output_schema={
        "type": "object",
        "properties": {
            "risk": {"enum": ["R0", "R1", "R2"]},
            "protected": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["risk", "protected"],
    },
    permissions=frozenset({"read:repository"}),
    invoke=_classify,
)
