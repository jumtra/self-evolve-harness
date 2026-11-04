from seh.contracts import DiagnosticLevel
from seh.doctor import DoctorContext, Finding
from seh.install_audit import (
    EXTERNAL_INSTALLER_MESSAGE,
    collect_registrations,
    find_duplicates,
)

CONFIG_PATH = ".harness/config.toml"
_LEVELS = {"ERROR": DiagnosticLevel.ERROR, "WARN": DiagnosticLevel.WARN}


def run(ctx: DoctorContext) -> list[Finding]:
    if not (ctx.root / CONFIG_PATH).is_file():
        return [
            Finding(
                "install_audit",
                DiagnosticLevel.INFO,
                "INSTALL_AUDIT_SKIPPED",
                "設定がないため二重登録の検査を省略しました",
            )
        ]
    duplicates = find_duplicates(collect_registrations(ctx.root))
    if not duplicates:
        return [
            Finding(
                "install_audit",
                DiagnosticLevel.INFO,
                "NO_DUPLICATE_REGISTRATIONS",
                "二重登録は見つかりませんでした",
            )
        ]
    findings: list[Finding] = []
    for dup in duplicates:
        sources = ", ".join(r.source for r in dup.registrations)
        message = (
            EXTERNAL_INSTALLER_MESSAGE
            if dup.reason == "EXTERNAL_INSTALLER_REGISTRATION"
            else f"{dup.kind} {dup.key} が重複しています"
        )
        findings.append(
            Finding(
                "install_audit",
                _LEVELS[dup.severity],
                dup.reason,
                f"{message} ({sources})",
                dup.registrations[0].source.split(":")[0],
            )
        )
    return findings
