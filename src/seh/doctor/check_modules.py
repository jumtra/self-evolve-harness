import shutil

from seh.config import ConfigError, load_config
from seh.contracts import DiagnosticLevel
from seh.doctor import DoctorContext, Finding
from seh.doctor.check_config import CONFIG_PATH
from seh.registry import ModuleRegistry, RegistryError, discover_manifests, modules_for_config


def _error(message: str) -> list[Finding]:
    return [Finding("modules", DiagnosticLevel.ERROR, "MODULE_RESOLUTION", message)]


def run(ctx: DoctorContext) -> list[Finding]:
    path = ctx.root / CONFIG_PATH
    if not path.is_file():
        return []
    try:
        config = load_config(path)
    except ConfigError:
        return []  # check_config が報告する
    try:
        manifests = discover_manifests()
        requested = modules_for_config(config.code_intelligence.provider, config.memory.provider)
    except RegistryError as exc:
        return _error(str(exc))
    plan = ModuleRegistry(manifests).resolve(requested)
    if plan.errors:
        return [f for e in plan.errors for f in _error(e)]
    by_id = {m.id: m for m in manifests}
    findings: list[Finding] = []
    for module_id in plan.enabled:
        command = by_id[module_id].health_command
        # 実行はしない: PATH 上の存在確認だけでオフライン・高速を保つ
        if command and shutil.which(command[0]) is None:
            findings.append(
                Finding(
                    "modules",
                    DiagnosticLevel.WARN,
                    "HEALTH_COMMAND_MISSING",
                    f"{module_id}: コマンド `{command[0]}` が PATH にありません",
                )
            )
    return findings
