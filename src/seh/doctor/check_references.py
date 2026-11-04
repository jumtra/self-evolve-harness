from seh.audit import find_dangling_references
from seh.contracts import DiagnosticLevel
from seh.doctor import DoctorContext, Finding

CONFIG_PATH = ".harness/config.toml"


def run(ctx: DoctorContext) -> list[Finding]:
    if not (ctx.root / CONFIG_PATH).is_file():
        return [
            Finding(
                "references",
                DiagnosticLevel.INFO,
                "REFERENCES_SKIPPED",
                "v2 未導入のため参照監査をスキップしました",
            )
        ]
    refs = find_dangling_references(ctx.root)
    if not refs:
        return [
            Finding(
                "references",
                DiagnosticLevel.INFO,
                "NO_DANGLING_REFERENCES",
                "削除済み Skill/Agent/Rule への参照はありません",
            )
        ]
    return [
        Finding(
            "references",
            DiagnosticLevel.ERROR,
            "DANGLING_REFERENCE",
            f"{r.path}:{r.line} {r.kind}:{r.name}",
            r.path,
        )
        for r in refs
    ]
