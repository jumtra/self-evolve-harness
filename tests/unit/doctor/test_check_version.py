from pathlib import Path

import pytest

from seh.contracts import DiagnosticLevel
from seh.doctor import DoctorContext, check_version


def test_missing_lock_is_info(tmp_path: Path) -> None:
    findings = check_version.run(DoctorContext(root=tmp_path, options={}))

    assert [(f.level, f.code) for f in findings] == [(DiagnosticLevel.INFO, "NO_LOCK")]


def test_matching_version_has_no_findings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(check_version, "__version__", "2.0.0a0")
    (tmp_path / ".harness").mkdir()
    (tmp_path / ".harness" / "generated.lock.json").write_text(
        '{"seh_version": "2.0.0a0"}', encoding="utf-8"
    )

    findings = check_version.run(DoctorContext(root=tmp_path, options={}))

    assert findings == []


def test_major_mismatch_is_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(check_version, "__version__", "2.0.0a0")
    (tmp_path / ".harness").mkdir()
    (tmp_path / ".harness" / "generated.lock.json").write_text(
        '{"seh_version": "1.4.0"}', encoding="utf-8"
    )

    findings = check_version.run(DoctorContext(root=tmp_path, options={}))

    assert [(f.level, f.code) for f in findings] == [(DiagnosticLevel.ERROR, "VERSION_MISMATCH")]


def test_minor_mismatch_is_warn(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(check_version, "__version__", "2.1.0")
    (tmp_path / ".harness").mkdir()
    (tmp_path / ".harness" / "generated.lock.json").write_text(
        '{"seh_version": "2.0.0a0"}', encoding="utf-8"
    )

    findings = check_version.run(DoctorContext(root=tmp_path, options={}))

    assert [(f.level, f.code) for f in findings] == [(DiagnosticLevel.WARN, "VERSION_MISMATCH")]


def test_corrupt_lock_is_error(tmp_path: Path) -> None:
    (tmp_path / ".harness").mkdir()
    (tmp_path / ".harness" / "generated.lock.json").write_text("{not json", encoding="utf-8")

    findings = check_version.run(DoctorContext(root=tmp_path, options={}))

    assert [(f.level, f.code) for f in findings] == [(DiagnosticLevel.ERROR, "LOCK_INVALID")]
