"""参照監査: v2 で削除される v1 の Skill / Agent / Rule 名へのダングリング参照を検出する。"""

import json
import os
import re
from collections.abc import Sequence
from dataclasses import dataclass
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Literal

Kind = Literal["skill", "agent", "rule"]

_KNOWN_PATHS = Path(__file__).parent / "migration" / "v1_known_paths.json"
_MAX_BYTES = 1024 * 1024
_TEXT_LIMIT = 200


@dataclass(frozen=True)
class DeletedNames:
    skills: frozenset[str]
    agents: frozenset[str]
    rules: frozenset[str]


@dataclass(frozen=True)
class Reference:
    path: str
    line: int
    kind: Kind
    name: str
    text: str


def _known_paths() -> dict[str, dict[str, str]]:
    return json.loads(_KNOWN_PATHS.read_text(encoding="utf-8"))["paths"]


def deleted_names() -> DeletedNames:
    skills: set[str] = set()
    agents: set[str] = set()
    rules: set[str] = set()
    for path, info in _known_paths().items():
        if info["v2_action"] != "DELETE":
            continue
        parts = path.split("/")
        if info["kind"] == "skill" and parts[-1] == "SKILL.md":
            skills.add(parts[-2])
        elif info["kind"] == "agent":
            agents.add(parts[-1].removesuffix(".md"))
        elif info["kind"] == "rule":
            rules.add(parts[-1].removesuffix(".md"))
    return DeletedNames(frozenset(skills), frozenset(agents), frozenset(rules))


def _v1_asset_paths() -> tuple[str, ...]:
    # 移行前の v1 資産は自分自身を参照しているだけなので監査対象外
    return tuple(
        path
        for path, info in sorted(_known_paths().items())
        if info["v2_action"] in {"DELETE", "MOVE", "REWRITE"}
    )


DEFAULT_EXCLUDES: tuple[str, ...] = (
    "docs/design/**",
    "docs/specs/**",
    "docs/decisions/**",
    "docs/v1-inventory.md",
    # v1 の計測記録とユーザーの記憶データは履歴として v1 名を含んでよい
    "docs/baseline/**",
    ".agent-memory/**",
    "docs/migration-v1-to-v2.md",
    "CHANGELOG.md",
    "src/seh/migration/**",
    "tests/fixtures/**",
    ".harness/backups/**",
    ".git/**",
    ".venv/**",
    "node_modules/**",
    "__pycache__/**",
    "**/__pycache__/**",
    "**/node_modules/**",
    "tests/unit/audit/**",
    "tests/unit/migration/**",
    "tests/integration/migration/**",
    *_v1_asset_paths(),
)


def _alt(names: frozenset[str]) -> str:
    return "|".join(re.escape(n) for n in sorted(names, key=lambda n: (-len(n), n)))


def _compile(names: DeletedNames) -> list[tuple[Kind, re.Pattern[str]]]:
    compiled: list[tuple[Kind, re.Pattern[str]]] = []

    def add(kind: Kind, group: frozenset[str], templates: Sequence[str]) -> None:
        if not group:
            return
        alt = _alt(group)
        compiled.extend((kind, re.compile(t.replace("NAMES", alt))) for t in templates)

    add(
        "skill",
        names.skills,
        (
            r"(?<![\w/.\-])/(NAMES)(?![\w\-/]|\.\w)",
            r"skills/(NAMES)/",
            r"`(NAMES)`\s*スキル",
            r"Skill\((NAMES)\)",
        ),
    )
    add(
        "agent",
        names.agents,
        (
            r"agents/(NAMES)\.md",
            r"subagent_type(?::\s*|\s*=\s*)[\"']?(NAMES)(?![\w\-])",
            r"`(NAMES)`\s*(?:エージェント|agent)",
        ),
    )
    add("rule", names.rules, (r"rules/(NAMES)\.md",))
    return compiled


def _excluded(rel: str, excludes: Sequence[str]) -> bool:
    return any(fnmatchcase(rel, pattern) for pattern in excludes)


def _read_text(path: Path) -> str | None:
    try:
        if path.stat().st_size > _MAX_BYTES:
            return None
        return path.read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def find_dangling_references(
    root: Path, *, excludes: Sequence[str] = DEFAULT_EXCLUDES
) -> list[Reference]:
    patterns = _compile(deleted_names())
    found: list[Reference] = []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        rel_dir = Path(dirpath).relative_to(root).as_posix()
        prefix = "" if rel_dir == "." else f"{rel_dir}/"
        dirnames[:] = sorted(d for d in dirnames if not _excluded(f"{prefix}{d}/", excludes))
        for filename in sorted(filenames):
            file = Path(dirpath, filename)
            rel = f"{prefix}{filename}"
            if file.is_symlink() or _excluded(rel, excludes):
                continue
            content = _read_text(file)
            if content is None:
                continue
            found.extend(_scan(rel, content, patterns))
    return found


def _scan(rel: str, content: str, patterns: list[tuple[Kind, re.Pattern[str]]]) -> list[Reference]:
    refs: list[Reference] = []
    for number, line in enumerate(content.splitlines(), start=1):
        seen: set[tuple[Kind, str]] = set()
        for kind, pattern in patterns:
            for match in pattern.finditer(line):
                key = (kind, match.group(1))
                if key not in seen:
                    seen.add(key)
                    refs.append(Reference(rel, number, kind, key[1], line[:_TEXT_LIMIT]))
    return refs
