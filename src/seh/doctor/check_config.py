from seh.config import ConfigError, load_config
from seh.contracts import DiagnosticLevel
from seh.doctor import DoctorContext, Finding

CONFIG_PATH = ".harness/config.toml"


def run(ctx: DoctorContext) -> list[Finding]:
    path = ctx.root / CONFIG_PATH
    if not path.is_file():
        return [
            Finding(
                "config",
                DiagnosticLevel.INFO,
                "NOT_CONFIGURED",
                "設定がありません。`seh init` で作成してください",
                CONFIG_PATH,
            )
        ]
    try:
        config = load_config(path)
    except ConfigError as exc:
        return [Finding("config", DiagnosticLevel.ERROR, "CONFIG_INVALID", str(exc), CONFIG_PATH)]
    return [
        Finding("config", DiagnosticLevel.WARN, "POLICY_WARNING", w, CONFIG_PATH)
        for w in config.policy_warnings()
    ]
