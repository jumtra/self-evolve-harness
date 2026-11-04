from pathlib import Path

import pytest

from seh.contracts import ModuleManifest
from seh.registry import (
    CORE_CAPABILITIES,
    ModuleRegistry,
    RegistryError,
    discover_manifests,
    load_manifest,
    modules_for_config,
)

BUILTIN_IDS = {
    "code-intelligence.codegraph",
    "code-intelligence.graphify",
    "code-intelligence.none",
    "memory.file",
    "memory.engram",
}


def test_builtin_manifests_all_load() -> None:
    manifests = discover_manifests()

    assert {m.id for m in manifests} == BUILTIN_IDS


def test_core_capabilities_are_fixed() -> None:
    expected = frozenset(["exec.local", "git.read", "git.write", "fs.read", "fs.write"])

    actual = CORE_CAPABILITIES

    assert actual == expected


def test_resolve_codegraph_with_memory_file_succeeds() -> None:
    registry = ModuleRegistry(discover_manifests())

    plan = registry.resolve(["code-intelligence.codegraph", "memory.file"])

    assert plan.errors == ()
    assert set(plan.enabled) == {"code-intelligence.codegraph", "memory.file"}
    assert plan.capabilities["code.affected_tests"] == "code-intelligence.codegraph"
    assert plan.capabilities["memory.store"] == "memory.file"


def test_graphify_does_not_provide_affected_tests() -> None:
    registry = ModuleRegistry(discover_manifests())

    plan = registry.resolve(["code-intelligence.graphify"])

    assert "code.affected_tests" not in plan.capabilities


def test_resolve_codegraph_and_graphify_conflicts() -> None:
    registry = ModuleRegistry(discover_manifests())

    plan = registry.resolve(["code-intelligence.codegraph", "code-intelligence.graphify"])

    assert "CONFLICT:code-intelligence.codegraph<->code-intelligence.graphify" in plan.errors
    assert plan.enabled == ()


def test_resolve_unknown_id() -> None:
    registry = ModuleRegistry(discover_manifests())

    plan = registry.resolve(["nope.module"])

    assert plan.errors == ("UNKNOWN_MODULE:nope.module",)
    assert plan.enabled == ()


def test_resolve_missing_dependency() -> None:
    manifest = ModuleManifest.from_mapping(
        {
            "id": "x.needs",
            "api_version": "1",
            "version": "1",
            "provides": ["x.cap"],
            "requires": ["nobody.provides"],
            "health_command": [],
        }
    )
    registry = ModuleRegistry([manifest])

    plan = registry.resolve(["x.needs"])

    assert plan.errors == ("MISSING_DEPENDENCY:x.needs:nobody.provides",)
    assert plan.enabled == ()


def test_resolve_orders_dependencies_first() -> None:
    base = ModuleManifest.from_mapping(
        {
            "id": "x.base",
            "api_version": "1",
            "version": "1",
            "provides": ["x.base"],
            "health_command": [],
        }
    )
    top = ModuleManifest.from_mapping(
        {
            "id": "x.top",
            "api_version": "1",
            "version": "1",
            "provides": ["x.top"],
            "requires": ["x.base", "exec.local"],
            "health_command": [],
        }
    )
    registry = ModuleRegistry([top, base])

    plan = registry.resolve(["x.top", "x.base"])

    assert plan.errors == ()
    assert plan.enabled == ("x.base", "x.top")


def test_resolve_cycle() -> None:
    a = ModuleManifest.from_mapping(
        {
            "id": "x.a",
            "api_version": "1",
            "version": "1",
            "provides": ["cap.a"],
            "requires": ["cap.b"],
            "health_command": [],
        }
    )
    b = ModuleManifest.from_mapping(
        {
            "id": "x.b",
            "api_version": "1",
            "version": "1",
            "provides": ["cap.b"],
            "requires": ["cap.a"],
            "health_command": [],
        }
    )
    registry = ModuleRegistry([a, b])

    plan = registry.resolve(["x.a", "x.b"])

    assert any(e.startswith("CYCLE:") for e in plan.errors)
    assert plan.enabled == ()


def test_resolve_api_version_mismatch() -> None:
    manifest = ModuleManifest.from_mapping(
        {
            "id": "x.future",
            "api_version": "99",
            "version": "1",
            "provides": ["x.cap"],
            "health_command": [],
        }
    )
    registry = ModuleRegistry([manifest])

    plan = registry.resolve(["x.future"])

    assert plan.errors == ("API_VERSION:x.future:99",)
    assert plan.enabled == ()


def test_resolve_duplicate_capability() -> None:
    a = ModuleManifest.from_mapping(
        {
            "id": "x.a",
            "api_version": "1",
            "version": "1",
            "provides": ["same.cap"],
            "health_command": [],
        }
    )
    b = ModuleManifest.from_mapping(
        {
            "id": "x.b",
            "api_version": "1",
            "version": "1",
            "provides": ["same.cap"],
            "health_command": [],
        }
    )
    registry = ModuleRegistry([a, b])

    plan = registry.resolve(["x.a", "x.b"])

    assert plan.errors == ("DUPLICATE_CAPABILITY:same.cap:x.a,x.b",)
    assert plan.enabled == ()


def test_discover_duplicate_id_raises(tmp_path: Path) -> None:
    (tmp_path / "one").mkdir()
    (tmp_path / "one" / "module.toml").write_text(
        'id = "memory.file"\napi_version = "1"\nversion = "1"\n'
        'provides = ["memory.store"]\nhealth_command = []\n'
    )

    with pytest.raises(RegistryError, match="memory.file"):
        discover_manifests(extra_dirs=[tmp_path])


def test_external_manifest_registers_and_resolves_without_core_change(tmp_path: Path) -> None:
    (tmp_path / "custom").mkdir()
    (tmp_path / "custom" / "module.toml").write_text(
        'id = "ext.custom"\napi_version = "1"\nversion = "0.1"\n'
        'provides = ["ext.cap"]\nrequires = ["git.read"]\nhealthcheck = []\n'
    )

    registry = ModuleRegistry(discover_manifests(extra_dirs=[tmp_path]))
    plan = registry.resolve(["ext.custom", "memory.file"])

    assert plan.errors == ()
    assert plan.capabilities["ext.cap"] == "ext.custom"


def test_load_manifest_does_not_execute_neighbor_python(tmp_path: Path) -> None:
    marker = tmp_path / "executed.marker"
    (tmp_path / "module.py").write_text(f"open({str(marker)!r}, 'w').write('x')\n")
    (tmp_path / "__init__.py").write_text(f"open({str(marker)!r}, 'w').write('x')\n")
    manifest_path = tmp_path / "module.toml"
    manifest_path.write_text(
        'id = "ext.safe"\napi_version = "1"\nversion = "1"\n'
        'provides = ["ext.cap"]\nhealth_command = []\n'
    )

    manifest = load_manifest(manifest_path)

    assert manifest.id == "ext.safe"
    assert not marker.exists()


def test_load_manifest_invalid_toml_raises_registry_error(tmp_path: Path) -> None:
    manifest_path = tmp_path / "module.toml"
    manifest_path.write_text("id = ")

    with pytest.raises(RegistryError):
        load_manifest(manifest_path)


def test_modules_for_config_maps_provider_names() -> None:
    result = modules_for_config("codegraph", "file")

    assert result == ["code-intelligence.codegraph", "memory.file"]


def test_modules_for_config_rejects_unknown_provider() -> None:
    with pytest.raises(RegistryError):
        modules_for_config("mystery", "file")
