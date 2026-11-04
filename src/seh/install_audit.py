"""外部インストーラ・手動設定・v1 残骸との Hook / Skill / MCP 二重登録を検出する（read-only）。"""

from __future__ import annotations

import json
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from seh.ownership import OwnershipManifest

__all__ = ["Duplicate", "Registration", "collect_registrations", "find_duplicates"]

Kind = Literal["hook", "skill", "mcp", "plugin"]

_SEH_COMMAND_MARKERS = ("seh hook", "seh-shim")
# v1 の安全 Hook（破壊コマンド・秘密情報・.env 保護・commit 検査）と同目的とみなす語
_SAFETY_KEYWORDS = ("rm -rf", "secret", ".env", "git commit")
_EXTERNAL_INSTALLERS = ("graphify", "codegraph")
_SKILL_DIRS = {"claude": ".claude/skills", "agy": ".agents/skills"}
_HOOK_FILES = {
    "claude": ".claude/settings.json",
    "agy": ".agents/hooks.json",
    "codex": ".codex/hooks.json",
}
EXTERNAL_INSTALLER_MESSAGE = (
    "seh は Provider を CLI 経由で使います。"
    "外部インストーラの登録と二重にならないよう確認してください"
)


@dataclass(frozen=True)
class Registration:
    host: str
    kind: Kind
    name: str
    source: str
    managed_by_seh: bool


@dataclass(frozen=True)
class Duplicate:
    kind: str
    key: str
    registrations: tuple[Registration, ...]
    severity: Literal["ERROR", "WARN"]
    reason: str


def _load_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _hooks(root: Path, host: str, rel: str) -> list[Registration]:
    path = root / rel
    if not path.is_file():
        return []
    data = _load_json(path)
    events = data.get("hooks", data)
    if not isinstance(events, dict):
        return []
    file_managed = OwnershipManifest.load(root).get(rel) is not None
    regs: list[Registration] = []
    for event, groups in events.items():
        if not isinstance(groups, list):
            continue
        for group in groups:
            if not isinstance(group, dict):
                continue
            matcher = str(group.get("matcher", ""))
            for hook in group.get("hooks", []):
                command = hook.get("command") if isinstance(hook, dict) else None
                if not isinstance(command, str):
                    continue
                managed = file_managed or any(m in command for m in _SEH_COMMAND_MARKERS)
                regs.append(
                    Registration(
                        host,
                        "hook",
                        f"{event}|{matcher}|{command}",
                        f"{rel}:hooks.{event}",
                        managed,
                    )
                )
    return regs


def _skills(root: Path, host: str, rel: str) -> list[Registration]:
    base = root / rel
    if not base.is_dir():
        return []
    manifest = OwnershipManifest.load(root)
    regs: list[Registration] = []
    for skill in sorted(p for p in base.iterdir() if p.is_dir()):
        files = (f for f in skill.rglob("*") if f.is_file())
        managed = any(manifest.get(f.relative_to(root).as_posix()) for f in files)
        regs.append(Registration(host, "skill", skill.name, f"{rel}/{skill.name}", managed))
    return regs


def _mcp(host: str, source: str, names: object) -> list[Registration]:
    if not isinstance(names, dict):
        return []
    return [Registration(host, "mcp", str(n), source, False) for n in names]


def _plugins(root: Path) -> list[Registration]:
    base = root / ".opencode" / "plugins"
    if not base.is_dir():
        return []
    manifest = OwnershipManifest.load(root)
    return [
        Registration(
            "opencode",
            "plugin",
            p.stem,
            f".opencode/plugins/{p.name}",
            manifest.get(p.relative_to(root).as_posix()) is not None,
        )
        for p in sorted(base.iterdir())
        if p.is_file()
    ]


def collect_registrations(root: Path) -> list[Registration]:
    regs: list[Registration] = []
    for host, rel in _HOOK_FILES.items():
        regs += _hooks(root, host, rel)
    for host, rel in _SKILL_DIRS.items():
        regs += _skills(root, host, rel)
    regs += _mcp("claude", ".mcp.json:mcpServers", _load_json(root / ".mcp.json").get("mcpServers"))
    codex = root / ".codex" / "config.toml"
    if codex.is_file():
        try:
            servers = tomllib.loads(codex.read_text(encoding="utf-8")).get("mcp_servers")
        except (OSError, tomllib.TOMLDecodeError):
            servers = None
        regs += _mcp("codex", ".codex/config.toml:mcp_servers", servers)
    regs += _mcp("opencode", "opencode.json:mcp", _load_json(root / "opencode.json").get("mcp"))
    regs += _plugins(root)
    return regs


def _split_hook(name: str) -> tuple[str, str, str]:
    event, matcher, command = name.split("|", 2)
    return event, matcher, command


def _hook_duplicates(regs: list[Registration]) -> list[Duplicate]:
    groups: dict[tuple[str, str, str], list[Registration]] = {}
    for reg in regs:
        if reg.kind != "hook":
            continue
        event, matcher, _ = _split_hook(reg.name)
        groups.setdefault((reg.host, event, matcher), []).append(reg)
    found: list[Duplicate] = []
    for (host, event, matcher), members in groups.items():
        by_command: dict[str, list[Registration]] = {}
        for reg in members:
            by_command.setdefault(_split_hook(reg.name)[2], []).append(reg)
        for command, same in by_command.items():
            if len(same) > 1:
                found.append(_hook_dup(host, event, matcher, command, tuple(same)))
        seh = [r for r in members if r.managed_by_seh]
        legacy = [
            r
            for r in members
            if not r.managed_by_seh
            and any(k in _split_hook(r.name)[2] for k in _SAFETY_KEYWORDS)
            and len(by_command[_split_hook(r.name)[2]]) == 1
        ]
        if seh and legacy:
            found.append(_hook_dup(host, event, matcher, "<safety>", (*seh, *legacy)))
    return found


def _hook_dup(
    host: str, event: str, matcher: str, command: str, regs: tuple[Registration, ...]
) -> Duplicate:
    return Duplicate("hook", f"{host}:{event}:{matcher}:{command}", regs, "ERROR", "DUPLICATE_HOOK")


def _skill_duplicates(regs: list[Registration]) -> list[Duplicate]:
    groups: dict[tuple[str, str], list[Registration]] = {}
    for reg in regs:
        if reg.kind == "skill":
            groups.setdefault((reg.host, reg.name), []).append(reg)
    return [
        Duplicate("skill", name, tuple(members), "ERROR", "DUPLICATE_SKILL")
        for (_, name), members in groups.items()
        if any(r.managed_by_seh for r in members) and any(not r.managed_by_seh for r in members)
    ]


def _mcp_duplicates(regs: list[Registration]) -> list[Duplicate]:
    groups: dict[str, list[Registration]] = {}
    for reg in regs:
        if reg.kind == "mcp":
            groups.setdefault(reg.name, []).append(reg)
    return [
        Duplicate("mcp", name, tuple(members), "WARN", "DUPLICATE_MCP")
        for name, members in groups.items()
        if len({r.source for r in members}) > 1
    ]


def _external_installer(regs: list[Registration]) -> list[Duplicate]:
    return [
        Duplicate(reg.kind, reg.name, (reg,), "WARN", "EXTERNAL_INSTALLER_REGISTRATION")
        for reg in regs
        if not reg.managed_by_seh and any(t in reg.name.lower() for t in _EXTERNAL_INSTALLERS)
    ]


def find_duplicates(regs: list[Registration]) -> list[Duplicate]:
    return [
        *_hook_duplicates(regs),
        *_skill_duplicates(regs),
        *_mcp_duplicates(regs),
        *_external_installer(regs),
    ]
