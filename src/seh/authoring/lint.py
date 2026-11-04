"""Authoring Guard の静的 lint。正本は本モジュール、ホスト生成物は各 HostAdapter.lint に委ねる。"""

import re
from collections.abc import Iterable, Mapping

from seh.contracts import (
    CanonicalSpec,
    Diagnostic,
    DiagnosticLevel,
    GeneratedPlan,
    HostAdapter,
    HostId,
    SkillSpec,
)
from seh.providers.hosts.claude import SKILL_KEYS as CLAUDE_SKILL_KEYS

ERROR = DiagnosticLevel.ERROR
WARN = DiagnosticLevel.WARN

# Authoring Contract（FR-057）。日英どちらの見出しでも可
_CONTRACT_SECTIONS: Mapping[str, tuple[str, ...]] = {
    "goal": ("Goal", "目的"),
    "inputs": ("Inputs", "入力"),
    "boundaries": ("Boundaries", "境界", "やらないこと"),
    "output": ("Output", "出力"),
    "feedback": ("Feedback", "検証", "フィードバック"),
}
_TRIGGER_WORDS = ("使う", "使用", "use when", "when", "を求められ")
_DESCRIPTION_MAX = 1024
_BROAD_TOOLS = frozenset({"Bash", "Write"})
_WRITE_TOOLS = frozenset({"Write", "Edit", "Bash", "MultiEdit", "NotebookEdit"})
_BUILTIN_NAMES = frozenset(
    {
        "help",
        "clear",
        "init",
        "review",
        "compact",
        "config",
        "cost",
        "doctor",
        "memory",
        "model",
        "security-review",
        "simplify",
        "loop",
        "schedule",
    }  # fmt: skip
)
_INSTRUCTIONS_MAX_CHARS = 4_000
_PROCEDURE_MAX_LINES = 15
_MIN_DUPLICATE_CHARS = 80
_TOOL_TOKEN = re.compile(r"([A-Za-z_]+)(?:\(([^)]*)\))?")
_NUMBERED = re.compile(r"^\s*\d+[.)]\s")
_FRONTMATTER = re.compile(r"\A---\n(.*?)\n---\n", re.DOTALL)
_TOP_KEY = re.compile(r"^([A-Za-z_][\w-]*)\s*:", re.MULTILINE)
_SHARED_SKILL_PATH = re.compile(r"^\.agents?/skills/[^/]+/SKILL\.md$")
_CLAUDE_ONLY_KEYS = CLAUDE_SKILL_KEYS - {"name", "description"}


def has_errors(diags: Iterable[Diagnostic]) -> bool:
    return any(d.level == ERROR for d in diags)


def lint_spec(spec: CanonicalSpec) -> list[Diagnostic]:
    diags: list[Diagnostic] = []
    for skill in spec.skills:
        diags += _lint_skill(skill)
    diags += _lint_ids(spec)
    diags += _lint_context_placement(spec)
    for agent in spec.agents:
        if agent.read_only and _WRITE_TOOLS & set(agent.tools):
            diags.append(
                Diagnostic(
                    ERROR,
                    "READ_ONLY_AGENT_HAS_WRITE_TOOL",
                    f"read_only の Agent {agent.id} に書き込み系 Tool が含まれる",
                )
            )
        if not agent.instructions.strip():
            diags.append(
                Diagnostic(
                    ERROR, "AGENT_INSTRUCTIONS_EMPTY", f"Agent {agent.id} の instructions が空"
                )
            )
    for rule in spec.rules:
        if not rule.always and not rule.globs:
            diags.append(
                Diagnostic(
                    WARN,
                    "RULE_WITHOUT_SCOPE",
                    f"Rule {rule.id} は always=False かつ globs 空。"
                    "AGY は model_decision、Claude は常時ロードになる",
                )
            )
    return diags


def _lint_skill(skill: SkillSpec) -> list[Diagnostic]:
    diags: list[Diagnostic] = []
    for section, names in _CONTRACT_SECTIONS.items():
        alternatives = "|".join(re.escape(n) for n in names)
        heading = re.compile(
            rf"^#{{2,3}}\s*(?:{alternatives})(?:\s|$|[:：(（])", re.MULTILINE | re.I
        )
        if not heading.search(skill.body):
            diags.append(
                Diagnostic(
                    ERROR,
                    f"SKILL_CONTRACT_MISSING:{section}",
                    f"Skill {skill.id} に '{names[0]}' 見出しが無い",
                )
            )
    lowered = skill.description.lower()
    if len(skill.description) > _DESCRIPTION_MAX:
        diags.append(Diagnostic(ERROR, "SKILL_DESCRIPTION_TOO_LONG", f"Skill {skill.id}"))
    if not any(word in lowered for word in _TRIGGER_WORDS):
        diags.append(
            Diagnostic(
                WARN,
                "SKILL_DESCRIPTION_NO_TRIGGER",
                f"Skill {skill.id} の description に「いつ使うか」が無い",
            )
        )
    unknown = sorted(set(skill.claude_frontmatter) - CLAUDE_SKILL_KEYS)
    if unknown:
        diags.append(
            Diagnostic(
                ERROR,
                "SKILL_UNKNOWN_FRONTMATTER_KEY",
                f"Skill {skill.id} に未知の frontmatter キー: {', '.join(unknown)}",
            )
        )
    if _has_broad_permission(skill.claude_frontmatter.get("allowed-tools")):
        diags.append(
            Diagnostic(
                ERROR,
                "SKILL_BROAD_TOOL_PERMISSION",
                f"Skill {skill.id} が Bash/Write を広域許可している（権限変更は high_risk）",
            )
        )
    return diags


def _has_broad_permission(value: object) -> bool:
    if value is None:
        return False
    text = " ".join(str(v) for v in value) if isinstance(value, (list, tuple)) else str(value)
    for name, arg in _TOOL_TOKEN.findall(text):
        if name in _BROAD_TOOLS and arg in ("", "*", ":*"):
            return True
    return False


def _lint_ids(spec: CanonicalSpec) -> list[Diagnostic]:
    diags: list[Diagnostic] = []
    seen: set[str] = set()
    ids = [s.id for s in spec.skills] + [a.id for a in spec.agents] + [r.id for r in spec.rules]
    for ident in ids:
        key = ident.lower()
        if key in seen:
            diags.append(Diagnostic(ERROR, "DUPLICATE_ID", f"id が重複: {ident}"))
        seen.add(key)
    for skill in spec.skills:
        if skill.id.lower() in _BUILTIN_NAMES:
            diags.append(
                Diagnostic(ERROR, "BUILTIN_NAME_COLLISION", f"Skill {skill.id} は組み込み名と衝突")
            )
    return diags


def _paragraphs(text: str) -> set[str]:
    normalized = (" ".join(p.split()) for p in re.split(r"\n\s*\n", text))
    return {p for p in normalized if len(p) >= _MIN_DUPLICATE_CHARS}


def _lint_context_placement(spec: CanonicalSpec) -> list[Diagnostic]:
    diags: list[Diagnostic] = []
    text = spec.instructions
    if len(text) > _INSTRUCTIONS_MAX_CHARS:
        diags.append(
            Diagnostic(
                WARN,
                "INSTRUCTIONS_TOO_LONG",
                f"常時指示が {_INSTRUCTIONS_MAX_CHARS} 文字超。手順は Skill へ移す",
            )
        )
    if sum(1 for line in text.splitlines() if _NUMBERED.match(line)) > _PROCEDURE_MAX_LINES:
        diags.append(
            Diagnostic(
                WARN,
                "LONG_PROCEDURE_IN_INSTRUCTIONS",
                f"常時指示に番号付き手順が {_PROCEDURE_MAX_LINES} 行超。Skill へ移す",
            )
        )
    shared = _paragraphs(text)
    bodies = [(s.id, s.body) for s in spec.skills] + [(r.id, r.body) for r in spec.rules]
    for ident, body in bodies:
        if shared & _paragraphs(body):
            diags.append(
                Diagnostic(
                    ERROR,
                    f"DUPLICATED_PROCEDURE:{ident}",
                    f"常時指示と {ident} に同一の手順がある。Skill/Rule へ移動し、"
                    "常時指示には参照だけを置く",
                )
            )
    return diags


def lint_generated(
    plans: Mapping[HostId, GeneratedPlan], adapters: Mapping[HostId, HostAdapter]
) -> list[Diagnostic]:
    diags: list[Diagnostic] = []
    for host, plan in plans.items():
        for d in adapters[host].lint(plan):
            diags.append(Diagnostic(d.level, f"{host.value}:{d.code}", d.message, d.path))
        for change in plan.changes:
            if change.content is None or not _SHARED_SKILL_PATH.match(change.path):
                continue
            match = _FRONTMATTER.match(change.content.decode("utf-8", errors="replace"))
            leaked = (
                sorted(set(_TOP_KEY.findall(match.group(1))) & _CLAUDE_ONLY_KEYS) if match else []
            )
            if leaked:
                diags.append(
                    Diagnostic(
                        ERROR,
                        "CLAUDE_KEY_LEAKED",
                        f"共有 Skill に Claude 固有キーが漏れている: {', '.join(leaked)}",
                        change.path,
                    )
                )
    return diags
