import json
import re

from seh import __version__
from seh.contracts import DiagnosticLevel
from seh.doctor import DoctorContext, Finding

LOCK_PATH = ".harness/generated.lock.json"
_MAJOR_MINOR = re.compile(r"^(\d+)\.(\d+)")


def _major_minor(version: str) -> tuple[int, int] | None:
    match = _MAJOR_MINOR.match(version)
    return (int(match[1]), int(match[2])) if match else None


def _finding(level: DiagnosticLevel, code: str, message: str) -> list[Finding]:
    return [Finding("version", level, code, message, LOCK_PATH)]


def run(ctx: DoctorContext) -> list[Finding]:
    path = ctx.root / LOCK_PATH
    if not path.is_file():
        return _finding(DiagnosticLevel.INFO, "NO_LOCK", "生成ロックがまだありません")
    try:
        locked = json.loads(path.read_text(encoding="utf-8"))["seh_version"]
        lock_version = _major_minor(locked)
    except (OSError, ValueError, KeyError, TypeError):
        return _finding(
            DiagnosticLevel.ERROR, "LOCK_INVALID", "ロックから seh_version を読めません"
        )
    current = _major_minor(__version__)
    if lock_version is None or current is None:
        return _finding(
            DiagnosticLevel.ERROR, "LOCK_INVALID", f"バージョン形式が不正です: {locked}"
        )
    if lock_version == current:
        return []
    detail = f"ロック {locked} と実行中 seh {__version__} が一致しません"
    if lock_version[0] != current[0]:
        return _finding(DiagnosticLevel.ERROR, "VERSION_MISMATCH", f"メジャー不一致: {detail}")
    return _finding(DiagnosticLevel.WARN, "VERSION_MISMATCH", f"マイナー不一致: {detail}")
