"""Tool の契約（Schema）・実装・必要権限を分離登録し、検証付きで呼び出す。

実行順: 存在確認 → 入力 Schema → パス検査 → Policy 認可 → 権限 → 実行 → 出力 Schema。
引数の内容は常にデータとして扱い、命令として解釈する経路を持たない（FR-048）。
"""

from __future__ import annotations

import posixpath
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote

import jsonschema

from seh.policy import Policy
from seh.redaction import mask_text

# Schema 内でパス引数を示す注釈（string、または items が string の array に付ける）
PATH_KEYWORD = "x-seh-path"


@dataclass(frozen=True)
class ToolContext:
    root: Path
    policy: Policy
    granted_permissions: frozenset[str]
    timeout_seconds: float = 120


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input_schema: Mapping[str, object]
    output_schema: Mapping[str, object]
    permissions: frozenset[str]
    invoke: Callable[[Mapping[str, object], ToolContext], Awaitable[Mapping[str, object]]]


class ToolError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


def _check_path(value: str, root: Path) -> None:
    for candidate in (value, unquote(value)):
        if not candidate or "\0" in candidate:
            raise ToolError("INVALID_INPUT", "invalid path")
        if (
            candidate.startswith("/")
            or "\\" in candidate
            or (len(candidate) > 1 and candidate[1] == ":")
        ):
            raise ToolError("INVALID_INPUT", f"absolute path not allowed: {value}")
        if ".." in posixpath.normpath(candidate).split("/") or ".." in candidate.split("/"):
            raise ToolError("INVALID_INPUT", f"parent traversal not allowed: {value}")
    real_root = root.resolve()
    if not (real_root / value).resolve().is_relative_to(real_root):
        raise ToolError("INVALID_INPUT", f"path escapes root: {value}")


def _validate_paths(
    schema: Mapping[str, object], arguments: Mapping[str, object], root: Path
) -> None:
    properties = schema.get("properties")
    if not isinstance(properties, Mapping):
        return
    for key, prop in properties.items():
        if key not in arguments or not isinstance(prop, Mapping):
            continue
        value = arguments[key]
        items = prop.get("items")
        if prop.get(PATH_KEYWORD) and isinstance(value, str):
            _check_path(value, root)
        elif isinstance(items, Mapping) and items.get(PATH_KEYWORD) and isinstance(value, list):
            for element in value:
                if isinstance(element, str):
                    _check_path(element, root)


class ToolRegistry:
    def __init__(self) -> None:
        self._specs: dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> None:
        if spec.name in self._specs:
            raise ValueError(f"tool already registered: {spec.name}")
        self._specs[spec.name] = spec

    def get(self, name: str) -> ToolSpec:
        try:
            return self._specs[name]
        except KeyError:
            raise ToolError("UNKNOWN_TOOL", f"unknown tool: {name}") from None

    def names(self) -> list[str]:
        return sorted(self._specs)

    async def execute(
        self, name: str, arguments: Mapping[str, object], ctx: ToolContext
    ) -> Mapping[str, object]:
        spec = self.get(name)
        try:
            jsonschema.validate(dict(arguments), dict(spec.input_schema))
        except jsonschema.ValidationError as exc:
            raise ToolError("INVALID_INPUT", mask_text(exc.message)) from None
        _validate_paths(spec.input_schema, arguments, ctx.root)
        decision = ctx.policy.authorize_tool(name)
        if not decision.allowed:
            raise ToolError("NOT_AUTHORIZED", decision.message)
        missing = spec.permissions - ctx.granted_permissions
        if missing:
            raise ToolError("PERMISSION_NOT_GRANTED", f"missing: {', '.join(sorted(missing))}")
        try:
            output = await spec.invoke(arguments, ctx)
        except ToolError:
            raise
        except Exception as exc:
            raise ToolError("TOOL_FAILED", mask_text(f"{type(exc).__name__}: {exc}")) from None
        try:
            jsonschema.validate(dict(output), dict(spec.output_schema))
        except jsonschema.ValidationError as exc:
            raise ToolError("INVALID_OUTPUT", mask_text(exc.message)) from None
        return output


def default_registry() -> ToolRegistry:
    # 各 Tool モジュールが registry を import するため循環を避けて遅延 import する
    from seh.tools.git_ops import DIFF_NAMES_SPEC, SCOPE_CHECK_SPEC
    from seh.tools.policy_checker import CLASSIFY_PATHS_SPEC
    from seh.tools.test_runner import TESTS_RUN_SPEC

    registry = ToolRegistry()
    for spec in (DIFF_NAMES_SPEC, SCOPE_CHECK_SPEC, CLASSIFY_PATHS_SPEC, TESTS_RUN_SPEC):
        registry.register(spec)
    return registry
