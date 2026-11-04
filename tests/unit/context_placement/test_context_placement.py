from pathlib import Path

from seh.doctor import DoctorContext
from seh.doctor.context_placement import run


def write(root: Path, path: str, text: str) -> None:
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")


def test_reports_delayed_size_and_placement_issues(tmp_path: Path) -> None:
    write(tmp_path, "CLAUDE.md", "# 手順\n" + "1. step\n" * 25)
    write(
        tmp_path,
        ".claude/skills/review/SKILL.md",
        "---\nname: review\ndescription: review\n---\nBody\n",
    )
    write(tmp_path, ".claude/commands/review.md", "Review\n")
    write(
        tmp_path,
        ".claude/skills/custom/SKILL.md",
        "---\nname: custom\ndescription: hello\n---\nDetails\n",
    )
    findings = run(DoctorContext(tmp_path, {"context": True}))
    codes = {f.code for f in findings}
    assert {
        "DELAYED_CONTEXT_SIZE",
        "LONG_PROCEDURE",
        "SKILL_COMMAND_DUPLICATE",
        "BUILTIN_NAME_COLLISION",
    } <= codes
    assert any("文字数" in f.message for f in findings if f.code == "DELAYED_CONTEXT_SIZE")


def test_short_instructions_and_distinct_names_are_clean(tmp_path: Path) -> None:
    write(tmp_path, "CLAUDE.md", "# Overview\nShort constraint\n")
    write(
        tmp_path,
        ".claude/skills/custom/SKILL.md",
        "---\nname: custom\ndescription: hello\n---\nDetails\n",
    )
    findings = run(DoctorContext(tmp_path, {"context": True}))
    assert [f.code for f in findings] == ["DELAYED_CONTEXT_SIZE"]
