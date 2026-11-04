"""Context の配置と遅延読み込み対象を検査する。"""

import re
from pathlib import Path

import yaml

from seh.authoring.inventory import _CLAUDE_BUILTINS
from seh.contracts import DiagnosticLevel
from seh.doctor import DoctorContext, Finding


def _skill_name(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    match = re.match(r"\A---\s*\n(.*?)\n---(?:\n|$)", text, re.DOTALL)
    if match:
        metadata = yaml.safe_load(match[1])
        if isinstance(metadata, dict) and isinstance(metadata.get("name"), str):
            return str(metadata["name"])
    return path.parent.name


def _delayed_text(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    if path.name == "SKILL.md":
        return re.sub(r"\A---\s*\n.*?\n---(?:\n|$)", "", text, count=1, flags=re.DOTALL)
    return text


def run(ctx: DoctorContext) -> list[Finding]:
    root = ctx.root
    skills = sorted(root.glob(".claude/skills/*/SKILL.md"))
    delayed = set(skills)
    for pattern in (
        ".claude/skills/*/references/**/*",
        ".harness/knowledge/**/*",
        ".claude/commands/**/*.md",
    ):
        delayed.update(p for p in root.glob(pattern) if p.is_file())
    text = "".join(_delayed_text(p) for p in sorted(delayed))
    findings = [
        Finding(
            "context_placement",
            DiagnosticLevel.INFO,
            "DELAYED_CONTEXT_SIZE",
            f"遅延 Context: 文字数 {len(text)} / バイト {len(text.encode('utf-8'))} / "
            f"行 {len(text.splitlines())}（{len(delayed)} 件）",
        )
    ]
    claude = root / "CLAUDE.md"
    if claude.is_file():
        content = claude.read_text(encoding="utf-8")
        steps = re.findall(r"(?m)^\s*(?:\d+[.)]|[-*]\s+\[[ xX]\])\s+", content)
        if len(steps) >= 20:
            findings.append(
                Finding(
                    "context_placement",
                    DiagnosticLevel.WARN,
                    "LONG_PROCEDURE",
                    "長い手順を Skill や参照資料への移動候補として確認してください",
                    "CLAUDE.md",
                )
            )
    commands = {p.stem.lower() for p in root.glob(".claude/commands/**/*.md") if p.is_file()}
    for path in skills:
        name = _skill_name(path).lower()
        relative = str(path.relative_to(root))
        if name in commands:
            findings.append(
                Finding(
                    "context_placement",
                    DiagnosticLevel.WARN,
                    "SKILL_COMMAND_DUPLICATE",
                    f"Skill と command の名前が重複しています: {name}",
                    relative,
                )
            )
        if name in _CLAUDE_BUILTINS:
            findings.append(
                Finding(
                    "context_placement",
                    DiagnosticLevel.WARN,
                    "BUILTIN_NAME_COLLISION",
                    f"Skill が組み込みコマンド名と衝突しています: {name}",
                    relative,
                )
            )
    return findings
