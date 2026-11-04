"""常時ロード Context の実測。定義は docs/baseline/v1-context.md §3 と同じ。"""

import re
from dataclasses import dataclass
from pathlib import Path

from seh.contracts import DiagnosticLevel
from seh.doctor import DoctorContext, Finding

ENABLED_BY_OPTION = "context"

# docs/baseline/v1-context.md §1 の合計（コミット 4c5ac19 基準）
V1_BASELINE_CHARS = 14835
V1_BASELINE_BYTES = 30135
V1_BASELINE_LINES = 503

_FRONTMATTER = re.compile(r"---\n(.*?)\n---\n", re.S)
_DESCRIPTION = re.compile(r"^description:([^\n]*)\n?(.*?)(?=^\S|\Z)", re.S | re.M)
_BLOCK_MARK = re.compile(r"^\s*[>|][-+]?\s*")


@dataclass(frozen=True)
class _Size:
    chars: int
    bytes: int
    lines: int


def _frontmatter(text: str) -> str:
    match = _FRONTMATTER.match(text)
    return match[1] if match else ""


def _whole_file(path: Path) -> _Size:
    text = path.read_text(encoding="utf-8")
    return _Size(len(text), len(text.encode()), text.count("\n"))


def _description(path: Path) -> _Size | None:
    meta = _frontmatter(path.read_text(encoding="utf-8"))
    if re.search(r"^disable-model-invocation:\s*true", meta, re.M):
        return None
    match = _DESCRIPTION.search(meta + "\n")
    if match is None:
        return None
    raw = (match[1] + "\n" + match[2]).rstrip("\n")
    folded = " ".join(
        line.strip() for line in _BLOCK_MARK.sub("", raw).splitlines() if line.strip()
    )
    return _Size(len(folded), len(folded.encode()), raw.count("\n") + 1)


def _is_always_loaded_rule(path: Path) -> bool:
    return re.search(r"^paths:", _frontmatter(path.read_text(encoding="utf-8")), re.M) is None


def _is_always_on_agents_rule(path: Path) -> bool:
    meta = _frontmatter(path.read_text(encoding="utf-8"))
    return re.search(r"^trigger:\s*always_on\s*$", meta, re.M) is not None


def _measure(root: Path) -> list[_Size]:
    sizes: list[_Size] = []
    sizes += [_whole_file(p) for p in (root / "CLAUDE.md", root / "AGENTS.md") if p.is_file()]
    sizes += [
        _whole_file(p) for p in sorted(root.glob(".claude/rules/*.md")) if _is_always_loaded_rule(p)
    ]
    sizes += [
        _whole_file(p)
        for p in sorted(root.glob(".agents/rules/*.md"))
        if _is_always_on_agents_rule(p)
    ]
    descriptions = [
        _description(p)
        for p in [
            *sorted(root.glob(".claude/skills/*/SKILL.md")),
            *sorted(root.glob(".claude/agents/*.md")),
        ]
    ]
    return sizes + [d for d in descriptions if d is not None]


def run(ctx: DoctorContext) -> list[Finding]:
    sizes = _measure(ctx.root)
    chars = sum(s.chars for s in sizes)
    size_bytes = sum(s.bytes for s in sizes)
    lines = sum(s.lines for s in sizes)
    findings = [
        Finding(
            "context",
            DiagnosticLevel.INFO,
            "CONTEXT_SIZE",
            f"常時 Context: 文字数 {chars} / バイト {size_bytes} / 行 {lines}（{len(sizes)} 件）",
        )
    ]
    if (chars, size_bytes, lines) > (0, 0, 0) and (
        chars > V1_BASELINE_CHARS or size_bytes > V1_BASELINE_BYTES or lines > V1_BASELINE_LINES
    ):
        findings.append(
            Finding(
                "context",
                DiagnosticLevel.WARN,
                "CONTEXT_ABOVE_V1_BASELINE",
                f"v1 基準（文字数 {V1_BASELINE_CHARS} / バイト {V1_BASELINE_BYTES} / "
                f"行 {V1_BASELINE_LINES}）を超えています",
            )
        )
    return findings
