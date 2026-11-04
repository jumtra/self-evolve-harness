"""計画適用後に各ホストが見る Skill を静的に算出する（ADR-0005）。"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import Path

from seh.contracts import HostId
from seh.providers.hosts.common import SHARED_SKILLS_DIR

# 各 Adapter の discover() が走査するディレクトリ。実ファイルがまだ無い計画段階で
# 同じ見え方を再現するため、ここに静的に持つ。
HOST_SKILL_DIRS: Mapping[HostId, tuple[str, ...]] = {
    HostId.CLAUDE: (".claude/skills",),
    HostId.ANTIGRAVITY: (SHARED_SKILLS_DIR, ".agent/skills"),
    HostId.CODEX: (SHARED_SKILLS_DIR,),
    HostId.OPENCODE: (".opencode/skills", ".claude/skills", SHARED_SKILLS_DIR),
}


def _skill_name_under(path: str, base: str) -> str | None:
    prefix, suffix = f"{base}/", "/SKILL.md"
    if not (path.startswith(prefix) and path.endswith(suffix)):
        return None
    name = path[len(prefix) : -len(suffix)]
    return name if name and "/" not in name else None


def static_discovery(
    hosts: Iterable[HostId], planned_paths: Iterable[str], existing_root: Path
) -> dict[HostId, dict[str, tuple[str, ...]]]:
    """host -> Skill 名 -> SKILL.md パス（計画 + 既存ファイルの和集合）。"""
    candidates = set(planned_paths)
    for dirs in HOST_SKILL_DIRS.values():
        for base in dirs:
            candidates.update(
                p.relative_to(existing_root).as_posix()
                for p in (existing_root / base).glob("*/SKILL.md")
            )
    seen: dict[HostId, dict[str, tuple[str, ...]]] = {}
    for host in hosts:
        found: dict[str, list[str]] = {}
        for base in HOST_SKILL_DIRS[host]:
            for path in sorted(candidates):
                name = _skill_name_under(path, base)
                if name is not None:
                    found.setdefault(name, []).append(path)
        seen[host] = {name: tuple(paths) for name, paths in sorted(found.items())}
    return seen


def discovery_collisions(seen: Mapping[HostId, Mapping[str, tuple[str, ...]]]) -> tuple[str, ...]:
    return tuple(
        f"DISCOVERY_COLLISION:{host.value}:{name}"
        for host, skills in seen.items()
        for name, paths in skills.items()
        if len(paths) > 1
    )
