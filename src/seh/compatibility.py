"""Evidence-based host compatibility report; discovery is static, never a live claim."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from seh.config import ConfigError, defaults, load_config
from seh.contracts import CanonicalSpec, DiagnosticLevel, HostAdapter, HostId, RenderContext
from seh.providers.hosts.permissions_map import map_permissions
from seh.spec_loader import SpecError, load_spec
from seh.sync import default_adapters

_COMMANDS = {
    HostId.CLAUDE: "claude",
    HostId.CODEX: "codex",
    HostId.OPENCODE: "opencode",
    HostId.ANTIGRAVITY: "agy",
}


def _skill(root: Path, path: str) -> dict[str, object]:
    resolved = (root / path).resolve()
    try:
        resolved.relative_to(root.resolve())
        digest = hashlib.sha256(resolved.read_bytes()).hexdigest()
    except (OSError, ValueError):
        digest = None
    return {"path": path, "sha256": digest, "effective_permissions": "UNVERIFIED"}


def _runtime_mode(root: Path) -> str:
    try:
        return load_config(root / ".harness/config.toml").runtime.mode
    except (FileNotFoundError, ConfigError):
        return defaults().runtime.mode


def build_report(
    root: Path, hosts: Sequence[HostId], *, adapters: Mapping[HostId, HostAdapter] | None = None
) -> dict[str, Any]:
    selected = default_adapters() if adapters is None else adapters
    reports: dict[str, object] = {}
    runtime_mode = _runtime_mode(root)
    spec_dir = root / ".harness/spec"
    status = "MISSING" if not spec_dir.exists() else "LOADED"
    spec_error: str | None = None
    spec: CanonicalSpec | None = None
    if status == "LOADED":
        try:
            spec = load_spec(spec_dir)
        except SpecError as exc:
            status, spec_error = "INVALID", str(exc)
    ctx = RenderContext(root, tuple(hosts), root.name)
    for host in hosts:
        adapter = selected[host]
        runtime = adapter.probe()
        # Empty rendering provides baseline capability descriptions only, never a claim
        # that absent or malformed canonical permissions were applied.
        plan = adapter.render(spec or CanonicalSpec("", (), (), ()), ctx)
        diagnostics = (*plan.diagnostics, *adapter.lint(plan))
        discovery = adapter.discover(root)
        skills = {
            name: [_skill(root, p) for p in paths] for name, paths in discovery.skills.items()
        }
        reasons = ["static discovery and effective permissions require live verification"]
        if not runtime.installed:
            reasons.append("CLI not installed")
        if runtime.policy_blocked:
            reasons.append("managed execution is policy blocked")
        if discovery.collisions:
            reasons.append("duplicate skill discovery: " + ", ".join(discovery.collisions))
        if status != "LOADED":
            reasons.append(f"canonical spec {status.lower()}; permissions cannot be assessed")
        if any(d.level is DiagnosticLevel.ERROR for d in diagnostics):
            reasons.append("render diagnostics contain errors")
        policy_blocked_in_mode = runtime.policy_blocked and runtime_mode == "managed"
        verdict = (
            "BLOCKED"
            if not runtime.installed
            or policy_blocked_in_mode
            or status == "INVALID"
            or any(d.level is DiagnosticLevel.ERROR for d in diagnostics)
            else "PARTIAL"
        )
        report: dict[str, object] = {
            "verdict": verdict,
            "managed_execution": "POLICY_BLOCKED" if runtime.policy_blocked else "AVAILABLE",
            "reasons": reasons,
            "canonical_spec": {
                "status": status,
                "path": ".harness/spec",
                "error": spec_error,
                "permissions": dict(spec.permissions) if spec is not None else None,
            },
            "permissions": {
                "requested": dict(spec.permissions) if spec is not None else None,
                "representable": (
                    dict(map_permissions(host, spec.permissions).permissions)
                    if spec is not None
                    else None
                ),
                "effective": "UNVERIFIED",
                "reason": "rendered configuration is not evidence of live host enforcement",
            },
            "diagnostics": [
                {"level": d.level.value, "code": d.code, "message": d.message, "path": d.path}
                for d in diagnostics
            ],
            "cli": {
                "command": _COMMANDS[host],
                "version": runtime.version,
                "installed": runtime.installed,
                "authenticated": runtime.authenticated,
            },
            "capabilities": [
                {"feature": c.feature, "level": c.level.value, "reason": c.reason}
                for c in plan.capabilities
            ],
            "cli_capabilities": {k: v.value for k, v in runtime.capabilities.items()},
            "skills": skills,
            "collisions": list(discovery.collisions),
            "hook_fallback": "seh missing from PATH: hook warns and allows",
        }
        if host is HostId.ANTIGRAVITY:
            report["surfaces"] = {
                "cli": "DETECTED" if runtime.installed else "NOT_DETECTED",
                "app": (
                    "DETECTED"
                    if any(
                        p.is_dir()
                        for p in (
                            Path("/Applications/Antigravity.app"),
                            Path.home() / "Applications/Antigravity.app",
                        )
                    )
                    else "NOT_DETECTED_AT_KNOWN_PATHS"
                ),
                "ide": "UNVERIFIED",
            }
        reports[host.value] = report
    return {
        "schema_version": 1,
        "hosts": reports,
        "graphify": {
            "status": "UNVERIFIED",
            "reason": "Graphify real CLI not tested; only fake output was tested (ADR-0004).",
        },
    }
