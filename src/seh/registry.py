from __future__ import annotations

import tomllib
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

from seh.contracts import ModuleManifest

CORE_CAPABILITIES = frozenset({"exec.local", "git.read", "git.write", "fs.read", "fs.write"})
SUPPORTED_API_VERSIONS = frozenset({"1"})

_CODE_INTEL_PROVIDERS = ("codegraph", "graphify", "none")
_MEMORY_PROVIDERS = ("file", "engram")


class RegistryError(Exception):
    pass


@dataclass(frozen=True)
class ResolvedPlan:
    enabled: tuple[str, ...]
    capabilities: Mapping[str, str]
    errors: tuple[str, ...]


def load_manifest(path: Path) -> ModuleManifest:
    """tomllib で読むだけ。manifest 隣のコードは import も実行もしない（任意コード実行の防止）。"""
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
        return ModuleManifest.from_mapping(data)
    except (OSError, tomllib.TOMLDecodeError, ValueError) as exc:
        raise RegistryError(f"manifest を読み込めません: {path}: {exc}") from exc


def discover_manifests(
    *, builtin: bool = True, extra_dirs: Sequence[Path] = ()
) -> list[ModuleManifest]:
    paths: list[Path] = []
    if builtin:
        root = resources.files("seh") / "modules"
        with resources.as_file(root) as modules_dir:
            paths.extend(sorted(modules_dir.glob("*/module.toml")))
            return _load_unique([*paths, *_extra_paths(extra_dirs)])
    return _load_unique(_extra_paths(extra_dirs))


def _extra_paths(extra_dirs: Sequence[Path]) -> list[Path]:
    return [p for d in extra_dirs for p in sorted(d.glob("*/module.toml"))]


def _load_unique(paths: Iterable[Path]) -> list[ModuleManifest]:
    seen: dict[str, Path] = {}
    manifests: list[ModuleManifest] = []
    for path in paths:
        manifest = load_manifest(path)
        if manifest.id in seen:
            raise RegistryError(
                f"module id が重複しています: {manifest.id} ({seen[manifest.id]} と {path})"
            )
        seen[manifest.id] = path
        manifests.append(manifest)
    return manifests


def modules_for_config(code_intel_provider: str, memory_provider: str) -> list[str]:
    if code_intel_provider not in _CODE_INTEL_PROVIDERS:
        raise RegistryError(f"未知の code intelligence provider: {code_intel_provider}")
    if memory_provider not in _MEMORY_PROVIDERS:
        raise RegistryError(f"未知の memory provider: {memory_provider}")
    return [f"code-intelligence.{code_intel_provider}", f"memory.{memory_provider}"]


class ModuleRegistry:
    def __init__(self, manifests: Sequence[ModuleManifest]) -> None:
        self._manifests = {m.id: m for m in manifests}

    def resolve(self, requested: Iterable[str]) -> ResolvedPlan:
        ids = list(dict.fromkeys(requested))
        errors = [f"UNKNOWN_MODULE:{i}" for i in ids if i not in self._manifests]
        selected = [self._manifests[i] for i in ids if i in self._manifests]

        errors += [
            f"API_VERSION:{m.id}:{m.api_version}"
            for m in selected
            if m.api_version not in SUPPORTED_API_VERSIONS
        ]
        errors += _conflict_errors(selected)
        providers, duplicate_errors = _capability_providers(selected)
        errors += duplicate_errors
        errors += _missing_dependency_errors(selected, providers)
        order, cycle_errors = _dependency_order(selected, providers)
        errors += cycle_errors

        if errors:
            return ResolvedPlan(enabled=(), capabilities={}, errors=tuple(errors))
        return ResolvedPlan(
            enabled=tuple(order),
            capabilities={cap: providers[cap][0] for cap in providers},
            errors=(),
        )


def _conflict_errors(selected: Sequence[ModuleManifest]) -> list[str]:
    enabled_ids = {m.id for m in selected}
    pairs = {
        tuple(sorted((m.id, other)))
        for m in selected
        for other in m.conflicts
        if other in enabled_ids
    }
    return [f"CONFLICT:{a}<->{b}" for a, b in sorted(pairs)]


def _capability_providers(
    selected: Sequence[ModuleManifest],
) -> tuple[dict[str, list[str]], list[str]]:
    providers: dict[str, list[str]] = {}
    for m in selected:
        for cap in m.provides:
            providers.setdefault(cap, []).append(m.id)
    errors = [
        f"DUPLICATE_CAPABILITY:{cap}:{','.join(sorted(ids))}"
        for cap, ids in sorted(providers.items())
        if len(ids) > 1
    ]
    return providers, errors


def _missing_dependency_errors(
    selected: Sequence[ModuleManifest], providers: Mapping[str, list[str]]
) -> list[str]:
    return [
        f"MISSING_DEPENDENCY:{m.id}:{cap}"
        for m in selected
        for cap in m.requires
        if cap not in CORE_CAPABILITIES and cap not in providers
    ]


def _dependency_order(
    selected: Sequence[ModuleManifest], providers: Mapping[str, list[str]]
) -> tuple[list[str], list[str]]:
    deps = {
        m.id: {providers[cap][0] for cap in m.requires if cap in providers} - {m.id}
        for m in selected
    }
    order: list[str] = []
    remaining = dict(deps)
    while remaining:
        ready = [i for i, d in remaining.items() if d <= set(order)]
        if not ready:
            return [], [f"CYCLE:{'->'.join(sorted(remaining))}"]
        for i in ready:
            order.append(i)
            del remaining[i]
    return order, []
