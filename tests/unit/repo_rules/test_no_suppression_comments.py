"""lint / 型チェッカーの抑制コメントが混入していないことを実リポジトリで検査する。"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SCAN_DIRS = ("src", "tests")
SUFFIXES = {".py", ".ts", ".sh"}
EXCLUDED_PREFIXES = ("tests/fixtures/",)

# 検出パターンを連結で組み立てるのは、このファイル自身に一致させないため
_HASH = "#" + " "
_SLASH = "//" + " "
PATTERNS = (
    _HASH + "no" + "qa",
    _HASH + "type: " + "ignore",
    _HASH + "pyright: " + "ignore",
    _HASH + "pyright:",
    _HASH + "fmt: " + "off",
    _SLASH + "@ts-" + "ignore",
    _SLASH + "eslint-" + "disable",
)


def _scan() -> list[str]:
    found: list[str] = []
    for top in SCAN_DIRS:
        for path in sorted((ROOT / top).rglob("*")):
            if path.suffix not in SUFFIXES or not path.is_file():
                continue
            rel = path.relative_to(ROOT).as_posix()
            if rel.startswith(EXCLUDED_PREFIXES):
                continue
            for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if any(p in line for p in PATTERNS):
                    found.append(f"{rel}:{lineno}")
    return found


def test_no_suppression_comments_in_repository() -> None:
    found = _scan()

    assert found == [], "suppression comments found:\n" + "\n".join(found)
