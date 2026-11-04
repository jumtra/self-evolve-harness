from pathlib import Path

import pytest

from seh.contracts import DiagnosticLevel
from seh.doctor import DoctorContext, check_modules


def test_codegraph_without_binary_on_path_warns_without_running_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / ".harness").mkdir()
    (tmp_path / ".harness" / "config.toml").write_text(
        '[code_intelligence]\nprovider = "codegraph"\n', encoding="utf-8"
    )
    monkeypatch.setenv("PATH", "")

    findings = check_modules.run(DoctorContext(root=tmp_path, options={}))

    assert [(f.level, f.code) for f in findings] == [
        (DiagnosticLevel.WARN, "HEALTH_COMMAND_MISSING")
    ]
    assert "codegraph" in findings[0].message
    assert "/" not in findings[0].message


def test_default_providers_have_no_findings(tmp_path: Path) -> None:
    (tmp_path / ".harness").mkdir()
    (tmp_path / ".harness" / "config.toml").write_text('profile = "balanced"\n', encoding="utf-8")

    findings = check_modules.run(DoctorContext(root=tmp_path, options={}))

    assert findings == []


def test_conflicting_modules_are_resolution_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / ".harness").mkdir()
    (tmp_path / ".harness" / "config.toml").write_text('profile = "balanced"\n', encoding="utf-8")
    monkeypatch.setattr(
        check_modules,
        "modules_for_config",
        lambda code_intel, memory: ["code-intelligence.codegraph", "code-intelligence.graphify"],
    )

    findings = check_modules.run(DoctorContext(root=tmp_path, options={}))

    assert DiagnosticLevel.ERROR in [f.level for f in findings]
    assert {f.code for f in findings} == {"MODULE_RESOLUTION"}
    assert any("CONFLICT" in f.message for f in findings)


def test_without_config_the_check_is_silent(tmp_path: Path) -> None:
    findings = check_modules.run(DoctorContext(root=tmp_path, options={}))

    assert findings == []
