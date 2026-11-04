from pathlib import Path

from seh.contracts import DiagnosticLevel
from seh.doctor import DoctorContext, check_config


def test_missing_config_is_info_pointing_to_seh_init(tmp_path: Path) -> None:
    findings = check_config.run(DoctorContext(root=tmp_path, options={}))

    assert [(f.level, f.code) for f in findings] == [(DiagnosticLevel.INFO, "NOT_CONFIGURED")]
    assert "seh init" in findings[0].message


def test_invalid_config_is_error_with_message(tmp_path: Path) -> None:
    (tmp_path / ".harness").mkdir()
    (tmp_path / ".harness" / "config.toml").write_text('profile = "bogus"\n', encoding="utf-8")

    findings = check_config.run(DoctorContext(root=tmp_path, options={}))

    assert [(f.level, f.code) for f in findings] == [(DiagnosticLevel.ERROR, "CONFIG_INVALID")]
    assert "profile" in findings[0].message


def test_valid_config_has_no_findings(tmp_path: Path) -> None:
    (tmp_path / ".harness").mkdir()
    (tmp_path / ".harness" / "config.toml").write_text('profile = "balanced"\n', encoding="utf-8")

    findings = check_config.run(DoctorContext(root=tmp_path, options={}))

    assert findings == []


def test_policy_warnings_are_reported_as_warn(tmp_path: Path) -> None:
    (tmp_path / ".harness").mkdir()
    (tmp_path / ".harness" / "config.toml").write_text(
        '[hosts]\nenabled = ["antigravity"]\n\n'
        '[runtime]\nmode = "managed"\nselected_host = "antigravity"\n',
        encoding="utf-8",
    )

    findings = check_config.run(DoctorContext(root=tmp_path, options={}))

    assert [(f.level, f.code) for f in findings] == [(DiagnosticLevel.WARN, "POLICY_WARNING")]
    assert "POLICY_BLOCKED" in findings[0].message
