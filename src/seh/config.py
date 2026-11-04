"""`.harness/config.toml` の型付きモデル・検証・読み書き。"""

import tomllib
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Literal, cast

import tomli_w

from seh.contracts import HostId

PROFILES = ("minimal", "balanced", "full")
_HOST_VALUES = tuple(h.value for h in HostId)


class ConfigError(ValueError):
    """設定の検証エラー。メッセージにはドット表記のキーパスを含める。"""


@dataclass(frozen=True)
class HostsConfig:
    enabled: tuple[HostId, ...]
    antigravity_surface: Literal["auto", "app", "cli", "ide"]
    antigravity_managed_cli: Literal["disabled", "enabled"]


@dataclass(frozen=True)
class RuntimeSecurity:
    require_worktree: bool = True
    command_allowlist: tuple[str, ...] = ("git", "python", "pytest")
    allow_network: bool = False
    trust_external_repo: bool = False


@dataclass(frozen=True)
class RuntimeConfig:
    mode: Literal["native", "managed"]
    backend: Literal["cli"]
    selected_host: str
    max_parallel: int
    max_attempts_per_unit: int = 3
    max_seconds_per_unit: int = 600
    max_total_seconds: int = 3600
    security: RuntimeSecurity = RuntimeSecurity()


@dataclass(frozen=True)
class CodeIntelConfig:
    provider: Literal["codegraph", "graphify", "none"]
    fallback: Literal["source", "stop"]


@dataclass(frozen=True)
class MemoryConfig:
    provider: Literal["file", "engram"]
    path: str = ".agent-memory"


@dataclass(frozen=True)
class EvaluationConfig:
    mode: Literal["manual", "required"]
    trials: int
    promotion_requires_holdout: bool


@dataclass(frozen=True)
class EvolutionConfig:
    mode: Literal["off", "propose", "auto_low_risk"]


@dataclass(frozen=True)
class AuthoringConfig:
    policy: Literal["required", "advisory"]
    require_eval_for_behavior_change: bool = True
    required_hosts: Literal["active"] | tuple[HostId, ...] = "active"
    require_ci_for_promote: bool = True


@dataclass(frozen=True)
class SdkConfig:
    enabled: bool = False


@dataclass(frozen=True)
class Config:
    profile: Literal["minimal", "balanced", "full"]
    hosts: HostsConfig
    runtime: RuntimeConfig
    code_intelligence: CodeIntelConfig
    memory: MemoryConfig
    evaluation: EvaluationConfig
    evolution: EvolutionConfig
    authoring: AuthoringConfig
    sdk: SdkConfig
    schema_version: int = 1

    @property
    def evolution_effective_mode(self) -> str:
        # 初期版では自律昇格させない（02 §6.1）
        return "propose" if self.evolution.mode == "auto_low_risk" else self.evolution.mode

    def policy_warnings(self) -> list[str]:
        warnings: list[str] = []
        if (
            self.runtime.selected_host == HostId.ANTIGRAVITY.value
            and self.runtime.mode == "managed"
            and self.hosts.antigravity_managed_cli == "disabled"
        ):
            warnings.append(
                "POLICY_BLOCKED: antigravity の managed 実行は "
                'hosts.antigravity.managed_cli = "disabled" のため実行時に拒否されます'
            )
        return warnings


def defaults(profile: str = "balanced") -> Config:
    if profile not in PROFILES:
        raise ConfigError(f"profile: {profile!r} は不正です（{', '.join(PROFILES)}）")
    p = cast(Literal["minimal", "balanced", "full"], profile)
    return Config(
        profile=p,
        hosts=HostsConfig((HostId.CLAUDE,), "auto", "disabled"),
        runtime=RuntimeConfig(
            mode="managed" if p == "full" else "native",
            backend="cli",
            selected_host="auto",
            max_parallel={"minimal": 1, "balanced": 2, "full": 3}[p],
        ),
        code_intelligence=CodeIntelConfig("none", "source"),
        memory=MemoryConfig("file"),
        evaluation=EvaluationConfig(
            mode="manual" if p == "minimal" else "required",
            trials=3,
            promotion_requires_holdout=p != "minimal",
        ),
        evolution=EvolutionConfig("off" if p == "minimal" else "propose"),
        authoring=AuthoringConfig("required"),
        sdk=SdkConfig(),
    )


# --- スキーマ表: ドットキー -> 種別 ---------------------------------------------

_Kind = tuple[Any, ...]


def _enum(*choices: str) -> _Kind:
    return ("enum", choices)


def _int(lo: int, hi: int) -> _Kind:
    return ("int", lo, hi)


_BOOL: _Kind = ("bool",)
_STR: _Kind = ("str",)
_HOSTS: _Kind = ("hosts",)
_STRS: _Kind = ("strs",)
_REQUIRED_HOSTS: _Kind = ("required_hosts",)
_SELECTED_HOST: _Kind = ("selected_host",)

_SCHEMA: dict[str, _Kind] = {
    "schema_version": _int(1, 1),
    "profile": _enum(*PROFILES),
    "hosts.enabled": _HOSTS,
    "hosts.antigravity.surface": _enum("auto", "app", "cli", "ide"),
    "hosts.antigravity.managed_cli": _enum("disabled", "enabled"),
    "runtime.mode": _enum("native", "managed"),
    "runtime.backend": _enum("cli"),
    "runtime.selected_host": _SELECTED_HOST,
    "runtime.max_parallel": _int(1, 16),
    "runtime.max_attempts_per_unit": _int(1, 10),
    "runtime.max_seconds_per_unit": _int(1, 86400),
    "runtime.max_total_seconds": _int(1, 604800),
    "runtime.security.require_worktree": _BOOL,
    "runtime.security.command_allowlist": _STRS,
    "runtime.security.allow_network": _BOOL,
    "runtime.security.trust_external_repo": _BOOL,
    "code_intelligence.provider": _enum("codegraph", "graphify", "none"),
    "code_intelligence.fallback": _enum("source", "stop"),
    "memory.provider": _enum("file", "engram"),
    "memory.path": _STR,
    "evaluation.mode": _enum("manual", "required"),
    "evaluation.trials": _int(1, 100),
    "evaluation.promotion_requires_holdout": _BOOL,
    "evolution.mode": _enum("off", "propose", "auto_low_risk"),
    "authoring.policy": _enum("required", "advisory"),
    "authoring.require_eval_for_behavior_change": _BOOL,
    "authoring.required_hosts": _REQUIRED_HOSTS,
    "authoring.require_ci_for_promote": _BOOL,
    "sdk.enabled": _BOOL,
}


def _validate_host_list(key: str, value: object) -> tuple[HostId, ...]:
    if not isinstance(value, (list, tuple)) or not value:
        raise ConfigError(f"{key}: 1 件以上のホスト名の配列が必要です")
    hosts: list[HostId] = []
    for item in cast("list[object] | tuple[object, ...]", value):
        if item not in _HOST_VALUES:
            raise ConfigError(f"{key}: 未知のホスト {item!r}（{', '.join(_HOST_VALUES)}）")
        host = HostId(cast(str, item))
        if host in hosts:
            raise ConfigError(f"{key}: ホスト {item!r} が重複しています")
        hosts.append(host)
    return tuple(hosts)


def _validate(key: str, value: object) -> object:
    kind = _SCHEMA[key]
    tag = kind[0]
    if tag == "bool":
        if not isinstance(value, bool):
            raise ConfigError(f"{key}: 真偽値が必要です")
        if key == "sdk.enabled" and value:
            raise ConfigError(f"{key}: SDK アダプターは v2.0 で未実装のため true にできません")
        return value
    if tag == "int":
        if isinstance(value, bool) or not isinstance(value, int):
            raise ConfigError(f"{key}: 整数が必要です")
        if not kind[1] <= value <= kind[2]:
            raise ConfigError(f"{key}: {kind[1]}..{kind[2]} の範囲外です（{value}）")
        return value
    if tag == "enum":
        if value not in kind[1]:
            raise ConfigError(f"{key}: {value!r} は不正です（{', '.join(kind[1])}）")
        return value
    if tag == "str":
        if not isinstance(value, str) or not value:
            raise ConfigError(f"{key}: 空でない文字列が必要です")
        if key == "memory.path" and (
            PurePosixPath(value).is_absolute()
            or PureWindowsPath(value).is_absolute()
            or ".." in PurePosixPath(value.replace("\\", "/")).parts
        ):
            raise ConfigError(f"{key}: リポジトリ内の相対パス（.. なし）が必要です（{value!r}）")
        return value
    if tag == "strs":
        if not isinstance(value, (list, tuple)) or not all(
            isinstance(v, str) and v for v in cast("list[object] | tuple[object, ...]", value)
        ):
            raise ConfigError(f"{key}: 文字列の配列が必要です")
        return tuple(cast("list[str] | tuple[str, ...]", value))
    if tag == "hosts":
        return _validate_host_list(key, value)
    if tag == "required_hosts":
        if value == "active":
            return "active"
        return _validate_host_list(key, value)
    # selected_host
    if value != "auto" and value not in _HOST_VALUES:
        raise ConfigError(f"{key}: {value!r} は不正です（auto, {', '.join(_HOST_VALUES)}）")
    return value


# --- フラット表現との相互変換 ---------------------------------------------------


def _to_flat(cfg: Config) -> dict[str, object]:
    return {
        "schema_version": cfg.schema_version,
        "profile": cfg.profile,
        "hosts.enabled": cfg.hosts.enabled,
        "hosts.antigravity.surface": cfg.hosts.antigravity_surface,
        "hosts.antigravity.managed_cli": cfg.hosts.antigravity_managed_cli,
        "runtime.mode": cfg.runtime.mode,
        "runtime.backend": cfg.runtime.backend,
        "runtime.selected_host": cfg.runtime.selected_host,
        "runtime.max_parallel": cfg.runtime.max_parallel,
        "runtime.max_attempts_per_unit": cfg.runtime.max_attempts_per_unit,
        "runtime.max_seconds_per_unit": cfg.runtime.max_seconds_per_unit,
        "runtime.max_total_seconds": cfg.runtime.max_total_seconds,
        "runtime.security.require_worktree": cfg.runtime.security.require_worktree,
        "runtime.security.command_allowlist": cfg.runtime.security.command_allowlist,
        "runtime.security.allow_network": cfg.runtime.security.allow_network,
        "runtime.security.trust_external_repo": cfg.runtime.security.trust_external_repo,
        "code_intelligence.provider": cfg.code_intelligence.provider,
        "code_intelligence.fallback": cfg.code_intelligence.fallback,
        "memory.provider": cfg.memory.provider,
        "memory.path": cfg.memory.path,
        "evaluation.mode": cfg.evaluation.mode,
        "evaluation.trials": cfg.evaluation.trials,
        "evaluation.promotion_requires_holdout": cfg.evaluation.promotion_requires_holdout,
        "evolution.mode": cfg.evolution.mode,
        "authoring.policy": cfg.authoring.policy,
        "authoring.require_eval_for_behavior_change": (
            cfg.authoring.require_eval_for_behavior_change
        ),
        "authoring.required_hosts": cfg.authoring.required_hosts,
        "authoring.require_ci_for_promote": cfg.authoring.require_ci_for_promote,
        "sdk.enabled": cfg.sdk.enabled,
    }


def _from_flat(f: dict[str, Any]) -> Config:
    return Config(
        schema_version=f["schema_version"],
        profile=f["profile"],
        hosts=HostsConfig(
            f["hosts.enabled"], f["hosts.antigravity.surface"], f["hosts.antigravity.managed_cli"]
        ),
        runtime=RuntimeConfig(
            mode=f["runtime.mode"],
            backend=f["runtime.backend"],
            selected_host=f["runtime.selected_host"],
            max_parallel=f["runtime.max_parallel"],
            max_attempts_per_unit=f["runtime.max_attempts_per_unit"],
            max_seconds_per_unit=f["runtime.max_seconds_per_unit"],
            max_total_seconds=f["runtime.max_total_seconds"],
            security=RuntimeSecurity(
                require_worktree=f["runtime.security.require_worktree"],
                command_allowlist=f["runtime.security.command_allowlist"],
                allow_network=f["runtime.security.allow_network"],
                trust_external_repo=f["runtime.security.trust_external_repo"],
            ),
        ),
        code_intelligence=CodeIntelConfig(
            f["code_intelligence.provider"], f["code_intelligence.fallback"]
        ),
        memory=MemoryConfig(f["memory.provider"], f["memory.path"]),
        evaluation=EvaluationConfig(
            f["evaluation.mode"],
            f["evaluation.trials"],
            f["evaluation.promotion_requires_holdout"],
        ),
        evolution=EvolutionConfig(f["evolution.mode"]),
        authoring=AuthoringConfig(
            policy=f["authoring.policy"],
            require_eval_for_behavior_change=f["authoring.require_eval_for_behavior_change"],
            required_hosts=f["authoring.required_hosts"],
            require_ci_for_promote=f["authoring.require_ci_for_promote"],
        ),
        sdk=SdkConfig(f["sdk.enabled"]),
    )


def _flatten_raw(raw: dict[str, Any], prefix: str = "") -> dict[str, object]:
    flat: dict[str, object] = {}
    for key, value in raw.items():
        path = f"{prefix}{key}"
        if isinstance(value, dict):
            if not any(k.startswith(f"{path}.") for k in _SCHEMA):
                raise ConfigError(f"{path}: 未知のキーです")
            flat.update(_flatten_raw(cast("dict[str, Any]", value), f"{path}."))
        elif path not in _SCHEMA:
            raise ConfigError(f"{path}: 未知のキーです")
        else:
            flat[path] = value
    return flat


def _check_consistency(cfg: Config) -> None:
    enabled = cfg.hosts.enabled
    selected = cfg.runtime.selected_host
    if selected != "auto" and HostId(selected) not in enabled:
        raise ConfigError(f"runtime.selected_host: {selected!r} が hosts.enabled に含まれません")
    required = cfg.authoring.required_hosts
    if required != "active" and not set(required) <= set(enabled):
        raise ConfigError("authoring.required_hosts: hosts.enabled の部分集合である必要があります")
    if cfg.runtime.max_seconds_per_unit > cfg.runtime.max_total_seconds:
        raise ConfigError(
            "runtime.max_seconds_per_unit: max_total_seconds 以下である必要があります"
        )


def load_config(path: Path) -> Config:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise  # 呼び出し側が「未設定」として扱う
    except (UnicodeDecodeError, OSError) as e:
        raise ConfigError(f"{path}: 読み込めません（{type(e).__name__}: {e}）") from e
    try:
        raw = tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"{path}: TOML として不正です（{e}）") from e
    given = _flatten_raw(raw)
    validated = {k: _validate(k, v) for k, v in given.items()}
    profile = cast(str, validated.get("profile", "balanced"))
    flat = _to_flat(defaults(profile))
    flat.update(validated)
    cfg = _from_flat(flat)
    _check_consistency(cfg)
    return cfg


def _to_toml_value(value: object) -> object:
    if isinstance(value, tuple):
        return [str(v) for v in cast("tuple[object, ...]", value)]
    return str(value) if isinstance(value, HostId) else value


def dump_config(cfg: Config) -> str:
    tree: dict[str, Any] = {}
    for key, value in _to_flat(cfg).items():
        *parents, leaf = key.split(".")
        node = tree
        for part in parents:
            node = node.setdefault(part, {})
        node[leaf] = _to_toml_value(value)
    return tomli_w.dumps(tree)


def set_value(cfg: Config, dotted_key: str, raw_value: str) -> Config:
    if dotted_key not in _SCHEMA:
        raise ConfigError(f"{dotted_key}: 未知のキーです")
    kind = _SCHEMA[dotted_key][0]
    parsed: object = raw_value
    if kind == "bool":
        if raw_value.lower() not in ("true", "false"):
            raise ConfigError(f"{dotted_key}: true / false を指定してください")
        parsed = raw_value.lower() == "true"
    elif kind == "int":
        try:
            parsed = int(raw_value)
        except ValueError as e:
            raise ConfigError(f"{dotted_key}: 整数が必要です（{raw_value!r}）") from e
    elif kind in ("hosts", "strs") or (kind == "required_hosts" and raw_value != "active"):
        parsed = [p.strip() for p in raw_value.split(",") if p.strip()]
    flat = _to_flat(cfg)
    flat[dotted_key] = _validate(dotted_key, parsed)
    return _from_flat(flat)


def config_diff(old: Config, new: Config) -> list[tuple[str, object, object]]:
    a, b = _to_flat(old), _to_flat(new)
    return [(k, a[k], b[k]) for k in a if a[k] != b[k]]


__all__ = [
    "AuthoringConfig",
    "CodeIntelConfig",
    "Config",
    "ConfigError",
    "EvaluationConfig",
    "EvolutionConfig",
    "HostsConfig",
    "MemoryConfig",
    "RuntimeConfig",
    "RuntimeSecurity",
    "SdkConfig",
    "config_diff",
    "defaults",
    "dump_config",
    "load_config",
    "set_value",
]
