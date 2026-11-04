"""オフライン診断フレームワーク。`check_<name>.py` を置くだけでチェックが増える。"""

import pkgutil
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from importlib import import_module
from pathlib import Path

from seh.contracts import DiagnosticLevel


@dataclass(frozen=True)
class Finding:
    check: str
    level: DiagnosticLevel
    code: str
    message: str
    path: str | None = None


@dataclass(frozen=True)
class DoctorContext:
    root: Path
    options: Mapping[str, object]


Check = Callable[[DoctorContext], list[Finding]]


def _gated(option: str, run: Check) -> Check:
    def gated(ctx: DoctorContext) -> list[Finding]:
        return run(ctx) if ctx.options.get(option) else []

    return gated


def discover_checks() -> list[tuple[str, Check]]:
    names = sorted(
        info.name.removeprefix("check_")
        for info in pkgutil.iter_modules(__path__)
        if info.name.startswith("check_")
    )
    checks: list[tuple[str, Check]] = []
    for name in names:
        module = import_module(f"{__name__}.check_{name}")
        option = getattr(module, "ENABLED_BY_OPTION", None)
        run: Check = module.run
        checks.append((name, _gated(option, run) if option else run))
    return checks


def run_doctor(ctx: DoctorContext) -> list[Finding]:
    findings: list[Finding] = []
    for name, run in discover_checks():
        try:
            findings.extend(run(ctx))
        except Exception as exc:  # 1 チェックの失敗で診断全体を止めない
            findings.append(
                Finding(
                    name, DiagnosticLevel.ERROR, "CHECK_CRASHED", f"{type(exc).__name__}: {exc}"
                )
            )
    return findings
