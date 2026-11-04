import os
import stat
from pathlib import Path

import pytest

from seh.cli import main
from seh.config import ConfigError, load_config


def _load(tmp_path: Path, body: str) -> None:
    path = tmp_path / "config.toml"
    path.write_text(body, encoding="utf-8")
    load_config(path)


def test_selected_host_must_be_in_enabled_hosts(tmp_path: Path) -> None:
    body = '[hosts]\nenabled = ["claude"]\n[runtime]\nselected_host = "codex"\n'

    with pytest.raises(ConfigError, match=r"runtime\.selected_host"):
        _load(tmp_path, body)


def test_required_hosts_must_be_subset_of_enabled_hosts(tmp_path: Path) -> None:
    body = '[hosts]\nenabled = ["claude"]\n[authoring]\nrequired_hosts = ["claude", "codex"]\n'

    with pytest.raises(ConfigError, match=r"authoring\.required_hosts"):
        _load(tmp_path, body)


def test_seconds_per_unit_must_not_exceed_total(tmp_path: Path) -> None:
    body = "[runtime]\nmax_seconds_per_unit = 900\nmax_total_seconds = 600\n"

    with pytest.raises(ConfigError, match=r"runtime\.max_seconds_per_unit"):
        _load(tmp_path, body)


def test_duplicate_enabled_hosts_are_rejected(tmp_path: Path) -> None:
    body = '[hosts]\nenabled = ["claude", "claude"]\n'

    with pytest.raises(ConfigError, match=r"hosts\.enabled"):
        _load(tmp_path, body)


@pytest.mark.parametrize("bad", ["../x", "/abs/path", "a/../../x"])
def test_memory_path_must_stay_inside_repository(tmp_path: Path, bad: str) -> None:
    with pytest.raises(ConfigError, match=r"memory\.path"):
        _load(tmp_path, f'[memory]\npath = "{bad}"\n')


def test_invalid_utf8_config_raises_config_error(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_bytes(b"\xff\xfe\x00bad")

    with pytest.raises(ConfigError):
        load_config(path)


def test_set_apply_keeps_existing_file_mode(tmp_path: Path) -> None:
    harness = tmp_path / ".harness"
    harness.mkdir()
    target = harness / "config.toml"
    target.write_text('profile = "balanced"\n')
    os.chmod(target, 0o644)

    code = main(["config", "set", "runtime.max_parallel", "5", "--root", str(tmp_path), "--apply"])

    assert code == 0
    assert stat.S_IMODE(target.stat().st_mode) == 0o644
