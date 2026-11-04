"""Validate permission requests without weakening unsupported restrictions."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from seh.contracts import Diagnostic, DiagnosticLevel, HostId


@dataclass(frozen=True)
class PermissionMapping:
    permissions: Mapping[str, str]
    diagnostics: tuple[Diagnostic, ...]


def map_permissions(host: HostId, permissions: Mapping[str, str]) -> PermissionMapping:
    # A generic write permission cannot safely be represented by command-prefix rules.
    supported = {
        HostId.CLAUDE: {"read", "write", "bash"},
        HostId.OPENCODE: {"read", "write", "bash"},
        HostId.CODEX: set(),
        HostId.ANTIGRAVITY: set(),
    }[host]
    diagnostics = tuple(
        Diagnostic(
            DiagnosticLevel.ERROR,
            "UNSUPPORTED_PERMISSION",
            f"{host.value} cannot safely map {name}={value}",
        )
        for name, value in permissions.items()
        if name not in supported or value not in {"allow", "ask", "deny"}
    )
    return PermissionMapping(
        {k: v for k, v in permissions.items() if k in supported and v in {"allow", "ask", "deny"}},
        diagnostics,
    )
