import sys
from pathlib import Path

import pytest

import seh.doctor
from seh.contracts import DiagnosticLevel
from seh.doctor import DoctorContext, Finding, discover_checks, run_doctor


def test_discover_checks_returns_check_modules_in_name_order() -> None:
    names = [name for name, _ in discover_checks()]

    assert names == sorted(names)
    assert {"config", "version", "modules", "context"} <= set(names)


def test_discover_checks_ignores_modules_without_check_prefix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "helper_fw_a.py").write_text("def run(ctx):\n    return []\n", encoding="utf-8")
    monkeypatch.setattr(seh.doctor, "__path__", [*seh.doctor.__path__, str(tmp_path)])

    names = [name for name, _ in discover_checks()]

    assert "helper_fw_a" not in names


def test_added_check_module_is_discovered_without_editing_a_list(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "check_fw_extra.py").write_text(
        "from seh.contracts import DiagnosticLevel\n"
        "from seh.doctor import Finding\n"
        "def run(ctx):\n"
        "    return [Finding('fw_extra', DiagnosticLevel.INFO, 'EXTRA', 'ok')]\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(seh.doctor, "__path__", [*seh.doctor.__path__, str(tmp_path)])
    monkeypatch.delitem(sys.modules, "seh.doctor.check_fw_extra", raising=False)

    findings = run_doctor(DoctorContext(root=tmp_path, options={}))

    assert "EXTRA" in [f.code for f in findings]


def test_enabled_by_option_check_runs_only_when_option_is_true(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "check_fw_gated.py").write_text(
        "from seh.contracts import DiagnosticLevel\n"
        "from seh.doctor import Finding\n"
        "ENABLED_BY_OPTION = 'fw_flag'\n"
        "def run(ctx):\n"
        "    return [Finding('fw_gated', DiagnosticLevel.INFO, 'GATED', 'ran')]\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(seh.doctor, "__path__", [*seh.doctor.__path__, str(tmp_path)])
    monkeypatch.delitem(sys.modules, "seh.doctor.check_fw_gated", raising=False)

    off = run_doctor(DoctorContext(root=tmp_path, options={"fw_flag": False}))
    on = run_doctor(DoctorContext(root=tmp_path, options={"fw_flag": True}))

    assert "GATED" not in [f.code for f in off]
    assert "GATED" in [f.code for f in on]


def test_crashing_check_becomes_error_finding_and_others_continue(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import seh.doctor.check_config as check_config

    def boom(ctx: DoctorContext) -> list[Finding]:
        raise RuntimeError("kaboom")

    monkeypatch.setattr(check_config, "run", boom)

    findings = run_doctor(DoctorContext(root=tmp_path, options={}))

    crashed = [f for f in findings if f.code == "CHECK_CRASHED"]
    assert len(crashed) == 1
    assert crashed[0].check == "config"
    assert crashed[0].level is DiagnosticLevel.ERROR
    assert "kaboom" in crashed[0].message
    assert "NO_LOCK" in [f.code for f in findings]
