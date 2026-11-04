"""書込 allowlist の glob 照合。判定の意味をここ1箇所に固定する（`*` は `/` を越えない）。"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence


def _char_class(pattern: str, start: int) -> tuple[str, int] | None:
    # start は "[" の位置。閉じ括弧が無ければ None（リテラル扱い）
    i = start + 1
    if i < len(pattern) and pattern[i] in "!^":
        i += 1
    if i < len(pattern) and pattern[i] == "]":
        i += 1
    end = pattern.find("]", i)
    if end == -1:
        return None
    body = pattern[start + 1 : end]
    negate = body[:1] in ("!", "^")
    if negate:
        body = body[1:]
    body = body.replace("\\", "\\\\")
    return f"[{'^' if negate else ''}{body}]", end + 1


def glob_to_regex(pattern: str) -> re.Pattern[str]:
    out: list[str] = []
    i = 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif pattern[i] == "*":
            out.append("[^/]*")
            i += 1
        elif pattern[i] == "?":
            out.append("[^/]")
            i += 1
        elif pattern[i] == "[" and (cls := _char_class(pattern, i)) is not None:
            out.append(cls[0])
            i = cls[1]
        else:
            out.append(re.escape(pattern[i]))
            i += 1
    return re.compile("".join(out))


def match_path(path: str, pattern: str) -> bool:
    return glob_to_regex(pattern).fullmatch(path) is not None


def _always_outside(path: str) -> bool:
    parts = path.split("/")
    return path.startswith("/") or ".." in parts or ".git" in parts


def outside_allowlist(paths: Iterable[str], allowlist: Sequence[str]) -> tuple[str, ...]:
    patterns = [glob_to_regex(g) for g in allowlist]
    return tuple(
        sorted(
            {p for p in paths if _always_outside(p) or not any(r.fullmatch(p) for r in patterns)}
        )
    )
