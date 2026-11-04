from pathlib import Path

from seh.contracts import DiagnosticLevel
from seh.doctor import DoctorContext, check_references


def _ctx(root: Path) -> DoctorContext:
    return DoctorContext(root=root, options={})


def _configure(root: Path) -> None:
    (root / ".harness").mkdir()
    (root / ".harness" / "config.toml").write_text("", encoding="utf-8")


def test_without_config_is_skipped_info(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_text("/brainstorm\n", encoding="utf-8")

    findings = check_references.run(_ctx(tmp_path))

    assert [(f.level, f.code) for f in findings] == [(DiagnosticLevel.INFO, "REFERENCES_SKIPPED")]


def test_reference_is_error_with_location(tmp_path: Path) -> None:
    _configure(tmp_path)
    (tmp_path / "a.md").write_text("x\n/brainstorm\n", encoding="utf-8")

    findings = check_references.run(_ctx(tmp_path))

    assert [(f.level, f.code, f.message, f.path) for f in findings] == [
        (DiagnosticLevel.ERROR, "DANGLING_REFERENCE", "a.md:2 skill:brainstorm", "a.md")
    ]


def test_no_references_is_info(tmp_path: Path) -> None:
    _configure(tmp_path)

    findings = check_references.run(_ctx(tmp_path))

    assert [(f.level, f.code) for f in findings] == [
        (DiagnosticLevel.INFO, "NO_DANGLING_REFERENCES")
    ]
