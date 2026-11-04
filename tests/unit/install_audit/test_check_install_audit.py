import json
from pathlib import Path

from seh.contracts import DiagnosticLevel
from seh.doctor import DoctorContext, check_install_audit


def test_missing_config_is_skipped_info(tmp_path: Path) -> None:
    findings = check_install_audit.run(DoctorContext(root=tmp_path, options={}))

    assert [(f.level, f.code) for f in findings] == [
        (DiagnosticLevel.INFO, "INSTALL_AUDIT_SKIPPED")
    ]


def test_configured_project_without_duplicates_is_info(tmp_path: Path) -> None:
    (tmp_path / ".harness").mkdir()
    (tmp_path / ".harness" / "config.toml").write_text('profile = "balanced"\n', encoding="utf-8")

    findings = check_install_audit.run(DoctorContext(root=tmp_path, options={}))

    assert [(f.level, f.code) for f in findings] == [
        (DiagnosticLevel.INFO, "NO_DUPLICATE_REGISTRATIONS")
    ]


def test_duplicates_map_to_findings_by_severity(tmp_path: Path) -> None:
    (tmp_path / ".harness").mkdir()
    (tmp_path / ".harness" / "config.toml").write_text('profile = "balanced"\n', encoding="utf-8")
    (tmp_path / ".claude").mkdir()
    entry = {"matcher": "Bash", "hooks": [{"type": "command", "command": "echo audit"}]}
    (tmp_path / ".claude" / "settings.json").write_text(
        json.dumps({"hooks": {"PreToolUse": [entry, entry]}}), encoding="utf-8"
    )
    (tmp_path / ".mcp.json").write_text(
        json.dumps({"mcpServers": {"codegraph": {"command": "codegraph"}}}), encoding="utf-8"
    )

    findings = check_install_audit.run(DoctorContext(root=tmp_path, options={}))

    assert sorted((f.level.value, f.code) for f in findings) == [
        ("ERROR", "DUPLICATE_HOOK"),
        ("WARN", "EXTERNAL_INSTALLER_REGISTRATION"),
    ]
    external = next(f for f in findings if f.code == "EXTERNAL_INSTALLER_REGISTRATION")
    assert "CLI 経由" in external.message
