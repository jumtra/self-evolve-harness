"""`.harness/spec/`（Host 非依存の正本）を CanonicalSpec に読み込む。"""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path

import yaml

from seh.contracts import AgentSpec, CanonicalSpec, RuleSpec, SkillSpec

__all__ = ["SpecError", "load_spec"]

_FRONTMATTER = re.compile(r"\A---\n(.*?)\n---\n?", re.DOTALL)
_SKILL_KEYS = frozenset({"description", "claude"})
_RULE_KEYS = frozenset({"description", "globs", "always"})
_AGENT_KEYS = frozenset({"description", "instructions", "tools", "read_only", "model", "effort"})


class SpecError(ValueError):
    """正本の形式違反。メッセージの先頭にファイルパスを含める。"""


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise SpecError(f"{path}: 読み込めません（{error}）") from error


def _yaml_mapping(path: Path, text: str) -> dict[str, object]:
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as error:
        raise SpecError(f"{path}: YAML として不正です（{error}）") from error
    if not isinstance(data, dict) or not all(isinstance(k, str) for k in data):
        raise SpecError(f"{path}: マッピングである必要があります")
    return data


def _split_frontmatter(path: Path) -> tuple[dict[str, object], str]:
    text = _read(path)
    match = _FRONTMATTER.match(text)
    if match is None:
        raise SpecError(f"{path}: frontmatter（--- で囲む YAML）が必要です")
    return _yaml_mapping(path, match.group(1)), text[match.end() :].lstrip("\n")


def _check_keys(path: Path, data: Mapping[str, object], allowed: frozenset[str]) -> None:
    unknown = sorted(set(data) - allowed)
    if unknown:
        raise SpecError(f"{path}: 未知のキー {unknown}（許可: {sorted(allowed)}）")


def _require(path: Path, data: Mapping[str, object], key: str, kind: type) -> object:
    if key not in data:
        raise SpecError(f"{path}: 必須キー {key!r} がありません")
    value = data[key]
    if not isinstance(value, kind):
        raise SpecError(f"{path}: {key!r} は {kind.__name__} である必要があります")
    return value


def _optional(
    path: Path, data: Mapping[str, object], key: str, kind: type, default: object
) -> object:
    return _require(path, data, key, kind) if key in data else default


def _str_list(
    path: Path, data: Mapping[str, object], key: str, *, required: bool
) -> tuple[str, ...]:
    if key not in data and not required:
        return ()
    items = _require(path, data, key, list)
    assert isinstance(items, list)
    if not all(isinstance(i, str) for i in items):
        raise SpecError(f"{path}: {key!r} の要素は文字列である必要があります")
    return tuple(items)


def _opt_str(path: Path, data: Mapping[str, object], key: str) -> str | None:
    value = _optional(path, data, key, str, None)
    return value if isinstance(value, str) else None


def _load_skill(skill_dir: Path, display: str) -> SkillSpec:
    skill_md = skill_dir / "SKILL.md"
    shown = Path(display)
    if not skill_md.is_file():
        raise SpecError(f"{shown}: SKILL.md がありません")
    meta, body = _split_frontmatter(skill_md)
    _check_keys(shown, meta, _SKILL_KEYS)
    description = _require(shown, meta, "description", str)
    claude = _optional(shown, meta, "claude", dict, {})
    assert isinstance(description, str) and isinstance(claude, dict)
    references = {
        path.relative_to(skill_dir).as_posix(): _read(path)
        for path in sorted(skill_dir.rglob("*"))
        if path.is_file() and path != skill_md
    }
    try:
        return SkillSpec(
            id=skill_dir.name,
            description=description,
            body=body,
            references=references,
            claude_frontmatter=claude,
        )
    except ValueError as error:
        raise SpecError(f"{shown}: {error}") from error


def _load_agent(path: Path) -> AgentSpec:
    data = _yaml_mapping(path, _read(path))
    _check_keys(path, data, _AGENT_KEYS)
    description = _require(path, data, "description", str)
    instructions = _require(path, data, "instructions", str)
    read_only = _require(path, data, "read_only", bool)
    assert isinstance(description, str) and isinstance(instructions, str)
    assert isinstance(read_only, bool)
    return AgentSpec(
        id=path.stem,
        description=description,
        instructions=instructions,
        tools=_str_list(path, data, "tools", required=True),
        read_only=read_only,
        model=_opt_str(path, data, "model"),
        effort=_opt_str(path, data, "effort"),
    )


def _load_rule(path: Path) -> RuleSpec:
    meta, body = _split_frontmatter(path)
    _check_keys(path, meta, _RULE_KEYS)
    description = _require(path, meta, "description", str)
    always = _optional(path, meta, "always", bool, False)
    assert isinstance(description, str) and isinstance(always, bool)
    return RuleSpec(
        id=path.stem,
        description=description,
        body=body,
        globs=_str_list(path, meta, "globs", required=False),
        always=always,
    )


def load_spec(spec_dir: Path) -> CanonicalSpec:
    core = spec_dir / "instructions" / "core.md"
    if not core.is_file():
        raise SpecError(f"{core}: 共通指示 instructions/core.md がありません")

    skills_dir = spec_dir / "skills"
    skill_dirs = (
        sorted(p for p in skills_dir.iterdir() if p.is_dir()) if skills_dir.is_dir() else []
    )
    agent_files = sorted((spec_dir / "agents").glob("*.yaml"))
    rule_files = sorted((spec_dir / "rules").glob("*.md"))
    permissions_file = spec_dir / "permissions.yaml"
    permissions = (
        _yaml_mapping(permissions_file, _read(permissions_file))
        if permissions_file.is_file()
        else {}
    )
    if any(not isinstance(k, str) or not isinstance(v, str) for k, v in permissions.items()):
        raise SpecError(f"{permissions_file}: permissions must map strings to strings")
    return CanonicalSpec(
        permissions={k: v for k, v in permissions.items() if isinstance(v, str)},
        instructions=_read(core),
        skills=tuple(_load_skill(d, f"skills/{d.name}/SKILL.md") for d in skill_dirs),
        agents=tuple(_load_agent(p) for p in agent_files),
        rules=tuple(_load_rule(p) for p in rule_files),
    )
