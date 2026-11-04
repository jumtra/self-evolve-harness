from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Protocol

from seh.contracts.common import Result
from seh.contracts.host import PlannedChange


@dataclass(frozen=True)
class HealthResult:
    ok: bool
    message: str
    evidence: tuple[str, ...] = ()


@dataclass(frozen=True)
class InstallContext:
    root: Path
    home: Path


_REQUIRED_KEYS = ("id", "api_version", "version", "provides")
_TUPLE_KEYS = ("provides", "requires", "conflicts", "permissions", "platforms")
_BOOL_KEYS = ("default_enabled", "opt_in", "network_access")


@dataclass(frozen=True)
class ModuleManifest:
    id: str
    api_version: str
    version: str
    provides: tuple[str, ...]
    requires: tuple[str, ...]
    conflicts: tuple[str, ...]
    permissions: tuple[str, ...]
    platforms: tuple[str, ...]
    default_enabled: bool
    opt_in: bool
    network_access: bool
    health_command: tuple[str, ...]

    @classmethod
    def from_mapping(cls, data: Mapping[str, object]) -> ModuleManifest:
        """必須キー欠落・型違いは ValueError。設計書 6.2 の `healthcheck` キーも受け付ける。"""
        for key in _REQUIRED_KEYS:
            if key not in data:
                raise ValueError(f"manifest missing required key: {key}")
        health_key = "health_command" if "health_command" in data else "healthcheck"
        if health_key not in data:
            raise ValueError("manifest missing required key: health_command")

        values: dict[str, object] = {}
        for key in ("id", "api_version", "version"):
            value = data[key]
            if not isinstance(value, str) or not value:
                raise ValueError(f"manifest key {key} must be a non-empty string")
            values[key] = value
        for key in _TUPLE_KEYS:
            values[key] = _str_tuple(key, data.get(key, ()))
        values["health_command"] = _str_tuple(health_key, data[health_key])
        for key in _BOOL_KEYS:
            value = data.get(key, False)
            if not isinstance(value, bool):
                raise ValueError(f"manifest key {key} must be a boolean")
            values[key] = value
        return cls(**values)  # type: ignore[arg-type]


def _str_tuple(key: str, value: object) -> tuple[str, ...]:
    if not isinstance(value, list | tuple) or not all(isinstance(v, str) for v in value):
        raise ValueError(f"manifest key {key} must be a list of strings")
    return tuple(value)


class Module(Protocol):
    id: str
    api_version: str

    def capabilities(self) -> set[str]: ...

    def healthcheck(self) -> HealthResult: ...

    def plan_install(self, ctx: InstallContext) -> list[PlannedChange]: ...

    def plan_uninstall(self, ctx: InstallContext) -> list[PlannedChange]: ...


class CodeIntelligenceProvider(Protocol):
    def index(self, root: Path) -> Result: ...

    def search_symbols(self, query: str) -> Result: ...

    def dependencies(self, symbol: str) -> Result: ...

    def change_impact(self, paths: list[str]) -> Result: ...

    def affected_tests(self, paths: list[str]) -> Result: ...

    def healthcheck(self) -> Result: ...


@dataclass(frozen=True)
class MemoryRecord:
    id: str
    type: Literal["user", "feedback", "project", "reference"]
    title: str
    body: str
    metadata: Mapping[str, object] = field(default_factory=dict)


class MemoryProvider(Protocol):
    def save(self, record: MemoryRecord) -> Result: ...

    def get(self, record_id: str) -> Result: ...

    def search(self, query: str) -> Result: ...

    def delete(self, record_id: str) -> Result: ...

    def list(self) -> Result: ...
