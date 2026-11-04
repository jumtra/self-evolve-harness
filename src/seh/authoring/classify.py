from __future__ import annotations

import json
import posixpath
import re
import subprocess
import tomllib
import unicodedata
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Any, cast

import yaml

from seh.contracts import AuthoringRisk


class TargetKind(StrEnum):
    SKILL = "skill"
    AGENT = "agent"
    RULE = "rule"
    INSTRUCTIONS = "instructions"
    HOOK = "hook"
    PERMISSIONS = "permissions"
    PROMPT = "prompt"
    SPEC_SOURCE = "spec_source"
    OTHER = "other"


AUTHORING_GLOBS: tuple[str, ...] = (
    ".claude/skills/**",
    ".claude/agents/**",
    ".claude/rules/**",
    ".claude/settings.json",
    ".claude/commands/**",
    "CLAUDE.md",
    "AGENTS.md",
    "GEMINI.md",
    ".agents/skills/**",
    ".agents/rules/**",
    ".agents/agents/**",
    ".agents/hooks.json",
    ".codex/**",
    ".opencode/agents/**",
    ".opencode/plugins/**",
    ".harness/spec/**",
    ".harness/prompts/**",
    "**/CLAUDE.md",
    "**/AGENTS.md",
)

_ROOT_INSTRUCTIONS = frozenset({"claude.md", "agents.md", "gemini.md"})
_NESTED_INSTRUCTIONS = frozenset({"claude.md", "agents.md"})
_DOC_SUFFIXES = frozenset({".md", ".mdc", ".markdown", ".txt"})
_STRUCTURED_SUFFIXES = frozenset({".json", ".toml", ".yaml", ".yml"})
_SCRIPT_SUFFIXES = frozenset(
    {".sh", ".bash", ".zsh", ".py", ".js", ".mjs", ".cjs", ".ts", ".rb", ".ps1"}
)
# 権限・実行・承認に関わる可能性のあるキーは部分一致で拾う（取りこぼしより過検出を選ぶ）。
_SENSITIVE_KEY_PARTS = (
    "tool",
    "permission",
    "sandbox",
    "approval",
    "hook",
    "mcp",
    "exec",
    "allow",
    "deny",
    "read_only",
    "readonly",
    "trust",
    "plugin",
)
_TYPO_MAX_CHARS = 20
_TYPO_MAX_RATIO_DENOMINATOR = 50  # 全体長の 2%
_IGNORED_PUNCTUATION = frozenset("、。，．,.！!？?；;")

_ALWAYS_HIGH = "always_high"
_DOC = "doc"
_STRUCTURED = "structured"
_AUTO = "auto"


@dataclass(frozen=True)
class FileChange:
    path: str
    before: str | None
    after: str | None


@dataclass(frozen=True)
class Classification:
    path: str
    kind: TargetKind
    risk: AuthoringRisk
    reasons: tuple[str, ...]


class _Unparseable(ValueError):
    pass


_RANK = {AuthoringRisk.TEXT_ONLY: 0, AuthoringRisk.BEHAVIORAL: 1, AuthoringRisk.HIGH_RISK: 2}


def _normalize_path(path: str) -> str | None:
    normalized = posixpath.normpath(path.replace("\\", "/")).lower()
    if normalized == ".." or normalized.startswith(("../", "/")):
        return None
    return normalized


def _under(path: str, prefix: str) -> bool:
    return fnmatchcase(path, f"{prefix}/**")


def _route(path: str) -> tuple[TargetKind, str] | None:
    name = posixpath.basename(path)
    if "/" not in path and name in _ROOT_INSTRUCTIONS:
        return TargetKind.INSTRUCTIONS, _ALWAYS_HIGH
    if "/" in path and name in _NESTED_INSTRUCTIONS:
        return TargetKind.INSTRUCTIONS, _DOC
    if _under(path, ".harness/spec/instructions"):
        return TargetKind.INSTRUCTIONS, _ALWAYS_HIGH
    if path == ".claude/settings.json":
        return TargetKind.PERMISSIONS, _STRUCTURED
    if path in (".agents/hooks.json", ".codex/hooks.json") or _under(path, ".opencode/plugins"):
        return TargetKind.HOOK, _ALWAYS_HIGH
    if _under(path, ".codex/rules"):
        return TargetKind.PERMISSIONS, _ALWAYS_HIGH
    if _under(path, ".codex/agents"):
        return TargetKind.AGENT, _AUTO
    if _under(path, ".codex"):
        return TargetKind.PERMISSIONS, _ALWAYS_HIGH
    prefixes = (
        (TargetKind.SKILL, (".claude/skills", ".agents/skills", ".harness/spec/skills")),
        (
            TargetKind.AGENT,
            (".claude/agents", ".agents/agents", ".opencode/agents", ".harness/spec/agents"),
        ),
        (TargetKind.RULE, (".claude/rules", ".agents/rules", ".harness/spec/rules")),
        (TargetKind.PROMPT, (".claude/commands", ".harness/prompts")),
        (TargetKind.SPEC_SOURCE, (".harness/spec",)),
    )
    for kind, dirs in prefixes:
        if any(_under(path, d) for d in dirs):
            return kind, _AUTO
    return None


def is_authoring_path(path: str) -> bool:
    normalized = _normalize_path(path)
    return normalized is not None and _route(normalized) is not None


def _is_sensitive(key: str) -> bool:
    lowered = key.lower()
    return any(part in lowered for part in _SENSITIVE_KEY_PARTS)


def _split_frontmatter(text: str) -> tuple[dict[str, object], str]:
    text = text.removeprefix("﻿")
    lines = text.split("\n")
    if lines[0].rstrip() != "---":
        return {}, text
    for i in range(1, len(lines)):
        if lines[i].rstrip() == "---":
            data = _load_yaml("\n".join(lines[1:i]))
            return data, "\n".join(lines[i + 1 :])
    raise _Unparseable("unterminated frontmatter")


def _load_yaml(text: str) -> dict[str, object]:
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as e:
        raise _Unparseable(str(e)) from e
    return _as_mapping(data)


def _as_mapping(data: object) -> dict[str, object]:
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise _Unparseable("top-level value is not a mapping")
    return {str(k): v for k, v in cast("dict[Any, object]", data).items()}


def _load_structured(text: str, suffix: str) -> dict[str, object]:
    try:
        if suffix == ".json":
            return _as_mapping(json.loads(text))
        if suffix == ".toml":
            return _as_mapping(tomllib.loads(text))
    except (ValueError, tomllib.TOMLDecodeError) as e:
        raise _Unparseable(str(e)) from e
    return _load_yaml(text)


def _changed_keys(before: Mapping[str, object], after: Mapping[str, object]) -> list[str]:
    keys = set(before) | set(after)
    return sorted(k for k in keys if before.get(k, _MISSING) != after.get(k, _MISSING))


_MISSING = object()


def _normalize_text(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    # 数値内の小数点・桁区切りは意味を持つので句読点として消さない。
    text = re.sub(r"(?<=\d)\.(?=\d)", "\x00", text)
    text = re.sub(r"(?<=\d),(?=\d)", "\x01", text)
    return "".join(c for c in text if not c.isspace() and c not in _IGNORED_PUNCTUATION)


def _edit_distance_within(a: str, b: str, limit: int) -> bool:
    if abs(len(a) - len(b)) > limit:
        return False
    inf = limit + 1
    prev = [j if j <= limit else inf for j in range(len(b) + 1)]
    for i in range(1, len(a) + 1):
        cur = [inf] * (len(b) + 1)
        if i <= limit:
            cur[0] = i
        lo, hi = max(1, i - limit), min(len(b), i + limit)
        for j in range(lo, hi + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            cur[j] = min(prev[j - 1] + cost, prev[j] + 1, cur[j - 1] + 1, inf)
        if min(cur[max(0, lo - 1) : hi + 1]) > limit:
            return False
        prev = cur
    return prev[len(b)] <= limit


def _is_typo_level(a: str, b: str) -> bool:
    limit = min(_TYPO_MAX_CHARS, max(len(a), len(b)) // _TYPO_MAX_RATIO_DENOMINATOR)
    if limit == 0:
        return False
    start = 0
    while start < min(len(a), len(b)) and a[start] == b[start]:
        start += 1
    end = 0
    while end < min(len(a), len(b)) - start and a[-1 - end] == b[-1 - end]:
        end += 1
    return _edit_distance_within(a[start : len(a) - end], b[start : len(b) - end], limit)


def _body_change(before: str, after: str) -> tuple[AuthoringRisk, str] | None:
    if before == after:
        return None
    norm_before, norm_after = _normalize_text(before), _normalize_text(after)
    if norm_before == norm_after:
        return AuthoringRisk.TEXT_ONLY, "BODY_WHITESPACE_OR_PUNCTUATION_ONLY"
    if _is_typo_level(norm_before, norm_after):
        return AuthoringRisk.TEXT_ONLY, "BODY_TYPO_ONLY"
    return AuthoringRisk.BEHAVIORAL, "BODY_CHANGED"


def _key_reasons(prefix: str, keys: Iterable[str]) -> list[tuple[AuthoringRisk, str]]:
    return [
        (
            AuthoringRisk.HIGH_RISK if _is_sensitive(k) else AuthoringRisk.BEHAVIORAL,
            f"{prefix}_KEY_CHANGED:{k}",
        )
        for k in keys
    ]


def _structured_findings(change: FileChange, suffix: str) -> list[tuple[AuthoringRisk, str]]:
    assert change.after is not None
    before = _load_structured(change.before, suffix) if change.before is not None else {}
    after = _load_structured(change.after, suffix)
    findings = _key_reasons(suffix.removeprefix(".").upper(), _changed_keys(before, after))
    return findings or [(AuthoringRisk.TEXT_ONLY, "STRUCTURED_FORMATTING_ONLY")]


def _doc_findings(change: FileChange) -> list[tuple[AuthoringRisk, str]]:
    assert change.after is not None
    before_fm, before_body = (
        _split_frontmatter(change.before) if change.before is not None else ({}, "")
    )
    after_fm, after_body = _split_frontmatter(change.after)
    findings = _key_reasons("FRONTMATTER", _changed_keys(before_fm, after_fm))
    if change.before is None:
        sensitive = [f for f in findings if f[0] is AuthoringRisk.HIGH_RISK]
        return [*sensitive, (AuthoringRisk.BEHAVIORAL, "NEW_FILE")]
    body = _body_change(before_body, after_body)
    if body is not None:
        findings.append(body)
    return findings or [(AuthoringRisk.TEXT_ONLY, "FORMATTING_ONLY")]


_ALWAYS_HIGH_REASONS = {
    TargetKind.INSTRUCTIONS: "SHARED_INSTRUCTIONS_CHANGED",
    TargetKind.HOOK: "HOOK_CHANGED",
    TargetKind.PERMISSIONS: "PERMISSION_CONFIG_CHANGED",
}


def _findings(
    change: FileChange, kind: TargetKind, mode: str, suffix: str
) -> list[tuple[AuthoringRisk, str]]:
    if mode == _AUTO:
        if suffix in _SCRIPT_SUFFIXES:
            return [(AuthoringRisk.HIGH_RISK, "SCRIPT_CHANGED")]
        if suffix in _STRUCTURED_SUFFIXES:
            mode = _STRUCTURED
        elif suffix in _DOC_SUFFIXES:
            mode = _DOC
        else:
            return [(AuthoringRisk.BEHAVIORAL, "OPAQUE_FILE_CHANGED")]
    if mode == _ALWAYS_HIGH:
        reason = _ALWAYS_HIGH_REASONS.get(kind, "HIGH_RISK_PATH_CHANGED")
        return [(AuthoringRisk.HIGH_RISK, reason)]
    try:
        if mode == _STRUCTURED:
            return _structured_findings(change, suffix)
        return _doc_findings(change)
    except _Unparseable:
        reason = "STRUCTURED_UNPARSEABLE" if mode == _STRUCTURED else "FRONTMATTER_UNPARSEABLE"
        return [(AuthoringRisk.HIGH_RISK, reason)]


def classify_change(change: FileChange) -> Classification | None:
    path = _normalize_path(change.path)
    route = _route(path) if path is not None else None
    if path is None or route is None:
        return None
    kind, mode = route
    if change.before is None and change.after is None:
        return Classification(change.path, kind, AuthoringRisk.TEXT_ONLY, ("NO_CHANGE",))
    if change.after is None:
        return Classification(change.path, kind, AuthoringRisk.HIGH_RISK, ("FILE_DELETED",))
    if change.before == change.after:
        return Classification(change.path, kind, AuthoringRisk.TEXT_ONLY, ("NO_CHANGE",))
    findings = _findings(change, kind, mode, posixpath.splitext(path)[1])
    if change.before is None and kind is TargetKind.AGENT:
        findings.append((AuthoringRisk.HIGH_RISK, "NEW_AGENT_FILE"))
    risk = max((r for r, _ in findings), key=_RANK.__getitem__)
    if risk is not AuthoringRisk.TEXT_ONLY:
        findings = [f for f in findings if f[0] is not AuthoringRisk.TEXT_ONLY]
    return Classification(change.path, kind, risk, tuple(reason for _, reason in findings))


def classify_changes(changes: Iterable[FileChange]) -> list[Classification]:
    results = (classify_change(c) for c in changes)
    return [c for c in results if c is not None]


def overall_risk(classes: Iterable[Classification]) -> AuthoringRisk | None:
    risks = [c.risk for c in classes]
    return max(risks, key=_RANK.__getitem__) if risks else None


def _git(root: Path, *args: str) -> bytes:
    return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True).stdout


def _decode(data: bytes) -> str:
    return data.decode("utf-8", errors="replace")


def _show(root: Path, ref: str, path: str) -> str:
    return _decode(_git(root, "show", f"{ref}:{path}"))


def _read_worktree(root: Path, path: str) -> str | None:
    try:
        return _decode((root / path).read_bytes())
    except OSError:
        return None


def changes_from_git(root: Path, base: str, head: str | None = "HEAD") -> list[FileChange]:
    """rename は --no-renames で削除+追加に分解する（移動で保護パスを迂回されないように）。"""
    refs = [base] if head is None else [base, head]
    if any(r.startswith("-") for r in refs):
        raise ValueError("git ref must not start with '-'")
    raw = _git(root, "diff", "--name-status", "-z", "--no-renames", *refs)
    tokens = _decode(raw).split("\0")
    entries = [(tokens[i], tokens[i + 1]) for i in range(0, len(tokens) - 1, 2)]
    if head is None:
        untracked = _decode(_git(root, "ls-files", "--others", "--exclude-standard", "-z"))
        entries += [("A", p) for p in untracked.split("\0") if p]
    changes: list[FileChange] = []
    for status, path in entries:
        before = None if status == "A" else _show(root, base, path)
        if status == "D":
            after = None
        elif head is None:
            after = _read_worktree(root, path)
        else:
            after = _show(root, head, path)
        changes.append(FileChange(path, before, after))
    return changes
