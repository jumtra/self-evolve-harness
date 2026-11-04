"""新規 Skill / Prompt 提案の重複判定と配置判断（04 §1・§2.1〜2.3）。

collect_inventory は read-only（subprocess・ホーム側の読み取りなし）。
decide は 04 §1 の表を上から順に適用し、最初に該当した規則で決める。
"""

from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Literal

import yaml

from seh.commands import GROUPS
from seh.providers.hosts.antigravity import AntigravityHostAdapter
from seh.providers.hosts.claude import ClaudeHostAdapter
from seh.providers.hosts.codex import CodexHostAdapter
from seh.providers.hosts.opencode import OpenCodeHostAdapter
from seh.spec_loader import SpecError, load_spec
from seh.tools.registry import default_registry

__all__ = [
    "InventoryDecision",
    "InventoryItem",
    "Match",
    "Placement",
    "Proposal",
    "collect_inventory",
    "decide",
    "exploration_record",
    "similarity",
]

SIMILARITY_THRESHOLD = 0.5
MAX_MATCHES = 5
Kind = Literal["skill", "agent", "tool", "cli", "mcp", "builtin"]

# Claude Code 組み込みコマンド。再実装を避けるための固定リスト
_CLAUDE_BUILTINS: tuple[str, ...] = (
    "agents",
    "clear",
    "compact",
    "config",
    "context",
    "cost",
    "doctor",
    "help",
    "hooks",
    "init",
    "mcp",
    "memory",
    "model",
    "permissions",
    "review",
    "status",
)

_FRONTMATTER = re.compile(r"\A---\n(.*?)\n---", re.DOTALL)
_TOKEN = re.compile(r"[a-z0-9]+|[぀-ヿ㐀-鿿]+")
_CJK = re.compile(r"[぀-ヿ㐀-鿿]")


class Placement(StrEnum):
    NOT_NEEDED = "not_needed"
    MODIFY_EXISTING = "modify_existing"
    TOOL = "tool"
    RULE = "rule"
    AGENT = "agent"
    RUNTIME = "runtime"
    NEW_SKILL = "new_skill"


@dataclass(frozen=True)
class Proposal:
    id: str
    description: str
    trigger_examples: tuple[str, ...]
    repeated: bool
    deterministic: bool
    always_needed: bool
    needs_isolation: bool
    branching_or_parallel: bool


@dataclass(frozen=True)
class InventoryItem:
    kind: Kind
    name: str
    source: str
    description: str


@dataclass(frozen=True)
class Match:
    item: InventoryItem
    score: float


@dataclass(frozen=True)
class InventoryDecision:
    placement: Placement
    matches: tuple[Match, ...]
    reasons: tuple[str, ...]
    evidence_refs: tuple[str, ...]


def _tokens(text: str) -> set[str]:
    result: set[str] = set()
    for run in _TOKEN.findall(unicodedata.normalize("NFKC", text).lower()):
        if _CJK.match(run) is None or len(run) == 1:
            result.add(run)
        else:
            result.update(run[i : i + 2] for i in range(len(run) - 1))
    return result


def similarity(left: str, right: str) -> float:
    a, b = _tokens(left), _tokens(right)
    union = a | b
    return len(a & b) / len(union) if union else 0.0


def _score(proposal: Proposal, item: InventoryItem) -> float:
    if proposal.id.strip().lower() == item.name.strip().lower():
        return 1.0
    query = " ".join((proposal.id, proposal.description, *proposal.trigger_examples))
    return similarity(query, f"{item.name} {item.description}")


def _frontmatter(path: Path) -> dict[str, object]:
    try:
        match = _FRONTMATTER.match(path.read_text(encoding="utf-8"))
        data = yaml.safe_load(match.group(1)) if match else None
    except (OSError, UnicodeDecodeError, yaml.YAMLError):
        return {}
    return data if isinstance(data, dict) else {}


def _description(path: Path) -> str:
    value = _frontmatter(path).get("description")
    return value if isinstance(value, str) else ""


def _host_skills(root: Path) -> list[InventoryItem]:
    adapters = (
        ClaudeHostAdapter(),
        AntigravityHostAdapter(),
        CodexHostAdapter(),
        OpenCodeHostAdapter(),
    )
    reports = [
        adapter.discover(root, env={})
        if isinstance(adapter, OpenCodeHostAdapter)
        else adapter.discover(root)
        for adapter in adapters
    ]
    items: list[InventoryItem] = []
    for report in reports:
        for name, paths in report.skills.items():
            items.append(InventoryItem("skill", name, paths[0], _description(root / paths[0])))
    return items


def _spec_items(root: Path) -> list[InventoryItem]:
    spec_dir = root / ".harness" / "spec"
    if not spec_dir.is_dir():
        return []
    try:
        spec = load_spec(spec_dir)
    except SpecError:
        return []
    items = [
        InventoryItem("skill", s.id, f".harness/spec/skills/{s.id}/SKILL.md", s.description)
        for s in spec.skills
    ]
    items += [
        InventoryItem("agent", a.id, f".harness/spec/agents/{a.id}.yaml", a.description)
        for a in spec.agents
    ]
    return items


def _claude_agents(root: Path) -> list[InventoryItem]:
    items: list[InventoryItem] = []
    for path in sorted((root / ".claude" / "agents").glob("*.md")):
        name = _frontmatter(path).get("name")
        items.append(
            InventoryItem(
                "agent",
                name if isinstance(name, str) else path.stem,
                path.relative_to(root).as_posix(),
                _description(path),
            )
        )
    return items


def _mcp_servers(root: Path) -> list[InventoryItem]:
    try:
        data = json.loads((root / ".mcp.json").read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        return []
    servers = data.get("mcpServers") if isinstance(data, dict) else None
    if not isinstance(servers, dict):
        return []
    return [InventoryItem("mcp", str(name), ".mcp.json", "") for name in servers]


def collect_inventory(root: Path) -> list[InventoryItem]:
    registry = default_registry()
    items = [
        *_spec_items(root),
        *_host_skills(root),
        *_claude_agents(root),
        *(
            InventoryItem("tool", name, "seh tools", registry.get(name).description)
            for name in registry.names()
        ),
        *(InventoryItem("cli", group, "seh cli", "") for group in GROUPS),
        *_mcp_servers(root),
        *(InventoryItem("builtin", name, "claude builtin", "") for name in _CLAUDE_BUILTINS),
    ]
    unique: dict[tuple[str, str], InventoryItem] = {}
    for item in items:
        unique.setdefault((item.kind, item.name), item)
    return list(unique.values())


def _ref(item: InventoryItem) -> str:
    if item.kind in ("skill", "agent"):
        return f"file:{item.source}"
    return f"{item.kind}:{item.name}"


def _top_matches(proposal: Proposal, inventory: Sequence[InventoryItem]) -> tuple[Match, ...]:
    scored = [Match(item, _score(proposal, item)) for item in inventory]
    positive = [m for m in scored if m.score > 0]
    positive.sort(key=lambda m: -m.score)
    return tuple(positive[:MAX_MATCHES])


def decide(proposal: Proposal, inventory: Sequence[InventoryItem]) -> InventoryDecision:
    matches = _top_matches(proposal, inventory)
    refs = tuple(_ref(m.item) for m in matches)

    def result(placement: Placement, *reasons: str) -> InventoryDecision:
        return InventoryDecision(placement, matches, reasons, refs)

    if not proposal.repeated:
        return result(Placement.NOT_NEEDED, "ONE_OFF")
    if proposal.deterministic:
        return result(Placement.TOOL, "DETERMINISTIC_WORK")
    if proposal.always_needed:
        return result(Placement.RULE, "ALWAYS_NEEDED_CONVENTION")
    if proposal.needs_isolation:
        agent = next(
            (m for m in matches if m.item.kind == "agent" and m.score >= SIMILARITY_THRESHOLD),
            None,
        )
        if agent is not None:
            return result(
                Placement.MODIFY_EXISTING, "NEEDS_ISOLATION", f"EXISTING_AGENT:{agent.item.name}"
            )
        return result(Placement.AGENT, "NEEDS_ISOLATION")
    if proposal.branching_or_parallel:
        return result(Placement.RUNTIME, "USE_WORKFLOW_RUNTIME")
    best = next(
        (m for m in matches if m.item.kind != "agent" and m.score >= SIMILARITY_THRESHOLD),
        None,
    )
    if best is None:
        return result(Placement.NEW_SKILL, "NO_EXISTING_ALTERNATIVE")
    alternative = f"EXISTING_ALTERNATIVE:{best.item.kind}:{best.item.name}"
    if best.item.kind == "skill":
        return result(Placement.MODIFY_EXISTING, alternative)
    return result(Placement.NOT_NEEDED, alternative)


def _relative(source: str, root: Path) -> str:
    try:
        return Path(source).relative_to(root).as_posix()
    except ValueError:
        return source


def exploration_record(decision: InventoryDecision, inventory_root: Path) -> dict[str, object]:
    modules = list(
        dict.fromkeys(_relative(m.item.source, inventory_root) for m in decision.matches)
    )
    return {
        "related_existing_modules": modules,
        "reuse_decision": decision.placement.value,
        "evidence_refs": list(decision.evidence_refs),
    }
