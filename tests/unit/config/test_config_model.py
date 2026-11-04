from pathlib import Path

import pytest

from seh.config import (
    Config,
    ConfigError,
    config_diff,
    defaults,
    dump_config,
    load_config,
    set_value,
)
from seh.contracts import HostId


def test_minimal_profile_defaults() -> None:
    cfg = defaults("minimal")

    assert cfg.profile == "minimal"
    assert cfg.runtime.mode == "native"
    assert cfg.runtime.max_parallel == 1
    assert cfg.evaluation.mode == "manual"
    assert cfg.evolution.mode == "off"
    assert cfg.memory.provider == "file"
    assert cfg.code_intelligence.provider == "none"


def test_balanced_profile_defaults() -> None:
    cfg = defaults()

    assert cfg.profile == "balanced"
    assert cfg.runtime.mode == "native"
    assert cfg.runtime.max_parallel == 2
    assert cfg.evaluation.mode == "required"
    assert cfg.evolution.mode == "propose"
    assert cfg.code_intelligence.provider == "none"
    assert cfg.hosts.enabled == (HostId.CLAUDE,)
    assert cfg.hosts.antigravity_managed_cli == "disabled"
    assert cfg.memory.path == ".agent-memory"
    assert cfg.sdk.enabled is False


def test_full_profile_defaults() -> None:
    cfg = defaults("full")

    assert cfg.runtime.mode == "managed"
    assert cfg.runtime.max_parallel == 3
    assert cfg.evolution.mode == "propose"


def test_runtime_security_defaults() -> None:
    sec = defaults().runtime.security

    assert sec.require_worktree is True
    assert sec.command_allowlist == ("git", "python", "pytest")
    assert sec.allow_network is False
    assert sec.trust_external_repo is False


def test_unknown_profile_is_rejected() -> None:
    with pytest.raises(ConfigError, match="profile"):
        defaults("huge")


def test_load_fills_missing_keys_from_profile(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text('profile = "full"\n\n[runtime]\nmax_parallel = 4\n')

    cfg = load_config(path)

    assert cfg.runtime.max_parallel == 4
    assert cfg.runtime.mode == "managed"
    assert cfg.evolution.mode == "propose"


def test_load_reads_nested_tables(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text(
        '[hosts]\nenabled = ["claude", "codex"]\n\n'
        '[hosts.antigravity]\nsurface = "cli"\n\n'
        "[runtime.security]\nallow_network = true\n\n"
        '[authoring]\nrequired_hosts = ["claude"]\n'
    )

    cfg = load_config(path)

    assert cfg.hosts.enabled == (HostId.CLAUDE, HostId.CODEX)
    assert cfg.hosts.antigravity_surface == "cli"
    assert cfg.runtime.security.allow_network is True
    assert cfg.authoring.required_hosts == (HostId.CLAUDE,)


def test_load_missing_file_raises_file_not_found(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_config(tmp_path / "absent.toml")


def test_load_unknown_key_reports_dotted_path(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text("[runtime]\nbogus = 1\n")

    with pytest.raises(ConfigError, match=r"runtime\.bogus"):
        load_config(path)


def test_load_unknown_nested_key_reports_dotted_path(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text("[runtime.security]\nbogus = true\n")

    with pytest.raises(ConfigError, match=r"runtime\.security\.bogus"):
        load_config(path)


def test_load_wrong_type_reports_dotted_path(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text('[runtime]\nmax_parallel = "two"\n')

    with pytest.raises(ConfigError, match=r"runtime\.max_parallel"):
        load_config(path)


def test_load_bool_is_not_accepted_as_int(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text("[runtime]\nmax_parallel = true\n")

    with pytest.raises(ConfigError, match=r"runtime\.max_parallel"):
        load_config(path)


def test_load_enum_outside_choices_reports_dotted_path(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text('[evaluation]\nmode = "sometimes"\n')

    with pytest.raises(ConfigError, match=r"evaluation\.mode"):
        load_config(path)


def test_load_unknown_host_in_list_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text('[hosts]\nenabled = ["vim"]\n')

    with pytest.raises(ConfigError, match=r"hosts\.enabled"):
        load_config(path)


@pytest.mark.parametrize(
    ("table", "key", "value"),
    [
        ("runtime", "max_parallel", 0),
        ("runtime", "max_parallel", 17),
        ("runtime", "max_attempts_per_unit", 11),
        ("evaluation", "trials", 101),
        ("evaluation", "trials", 0),
    ],
)
def test_load_out_of_range_reports_dotted_path(
    tmp_path: Path, table: str, key: str, value: int
) -> None:
    path = tmp_path / "config.toml"
    path.write_text(f"[{table}]\n{key} = {value}\n")

    with pytest.raises(ConfigError, match=rf"{table}\.{key}"):
        load_config(path)


def test_load_invalid_toml_raises_config_error(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text("[runtime\n")

    with pytest.raises(ConfigError):
        load_config(path)


def test_load_sdk_enabled_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text("[sdk]\nenabled = true\n")

    with pytest.raises(ConfigError, match="SDK アダプターは v2.0 で未実装"):
        load_config(path)


def test_auto_low_risk_is_accepted_but_effective_mode_is_propose(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text('[evolution]\nmode = "auto_low_risk"\n')

    cfg = load_config(path)

    assert cfg.evolution.mode == "auto_low_risk"
    assert cfg.evolution_effective_mode == "propose"


def test_effective_mode_passes_through_other_modes() -> None:
    assert defaults("minimal").evolution_effective_mode == "off"


def test_antigravity_managed_with_disabled_cli_yields_policy_warning(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text('[runtime]\nmode = "managed"\nselected_host = "antigravity"\n')

    cfg = load_config(path)

    warnings = cfg.policy_warnings()
    assert len(warnings) == 1
    assert "POLICY_BLOCKED" in warnings[0]


def test_antigravity_managed_with_enabled_cli_has_no_warning(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text(
        '[runtime]\nmode = "managed"\nselected_host = "antigravity"\n\n'
        '[hosts.antigravity]\nmanaged_cli = "enabled"\n'
    )

    assert load_config(path).policy_warnings() == []


def test_default_config_has_no_policy_warning() -> None:
    assert defaults().policy_warnings() == []


def test_dump_then_load_round_trips(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    original = set_value(defaults("full"), "hosts.enabled", "claude,codex")
    original = set_value(original, "authoring.required_hosts", "codex")

    path.write_text(dump_config(original))
    reloaded = load_config(path)

    assert reloaded == original


def test_dump_outputs_every_key() -> None:
    text = dump_config(defaults())

    assert "[runtime.security]" in text
    assert "command_allowlist" in text
    assert 'required_hosts = "active"' in text
    assert "schema_version = 1" in text


def test_set_value_converts_int() -> None:
    cfg = set_value(defaults(), "runtime.max_parallel", "5")

    assert cfg.runtime.max_parallel == 5


def test_set_value_converts_bool() -> None:
    cfg = set_value(defaults(), "runtime.security.allow_network", "true")

    assert cfg.runtime.security.allow_network is True


def test_set_value_converts_comma_separated_hosts() -> None:
    cfg = set_value(defaults(), "hosts.enabled", "claude, codex")

    assert cfg.hosts.enabled == (HostId.CLAUDE, HostId.CODEX)


def test_set_value_converts_string_list() -> None:
    cfg = set_value(defaults(), "runtime.security.command_allowlist", "git,ruff")

    assert cfg.runtime.security.command_allowlist == ("git", "ruff")


def test_set_value_required_hosts_active_keyword() -> None:
    cfg = set_value(defaults(), "authoring.required_hosts", "active")

    assert cfg.authoring.required_hosts == "active"


def test_set_value_unknown_key_is_rejected() -> None:
    with pytest.raises(ConfigError, match=r"runtime\.nope"):
        set_value(defaults(), "runtime.nope", "1")


def test_set_value_bad_int_is_rejected() -> None:
    with pytest.raises(ConfigError, match=r"runtime\.max_parallel"):
        set_value(defaults(), "runtime.max_parallel", "many")


def test_set_value_out_of_range_is_rejected() -> None:
    with pytest.raises(ConfigError, match=r"runtime\.max_parallel"):
        set_value(defaults(), "runtime.max_parallel", "99")


def test_set_value_sdk_enabled_is_rejected() -> None:
    with pytest.raises(ConfigError, match="SDK"):
        set_value(defaults(), "sdk.enabled", "true")


def test_set_value_does_not_mutate_original() -> None:
    original = defaults()

    set_value(original, "runtime.max_parallel", "5")

    assert original.runtime.max_parallel == 2


def test_config_diff_lists_changed_keys() -> None:
    old = defaults()
    new = set_value(old, "runtime.max_parallel", "5")

    assert config_diff(old, new) == [("runtime.max_parallel", 2, 5)]


def test_config_diff_is_empty_for_equal_configs() -> None:
    assert config_diff(defaults(), defaults()) == []


def test_config_is_frozen() -> None:
    cfg: Config = defaults()

    with pytest.raises(AttributeError):
        cfg.profile = "full"  # type: ignore[misc]
