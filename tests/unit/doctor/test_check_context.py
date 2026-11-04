from pathlib import Path

from seh.contracts import DiagnosticLevel
from seh.doctor import DoctorContext, check_context


def test_measures_always_loaded_context(tmp_path: Path) -> None:
    (tmp_path / "CLAUDE.md").write_text("あいう\nxy\n", encoding="utf-8")
    (tmp_path / ".claude" / "rules").mkdir(parents=True)
    (tmp_path / ".claude" / "rules" / "always.md").write_text("abc\n", encoding="utf-8")
    (tmp_path / ".claude" / "rules" / "scoped.md").write_text(
        "---\npaths:\n  - src/**\n---\n" + "z" * 1000 + "\n", encoding="utf-8"
    )
    (tmp_path / ".claude" / "skills" / "visible").mkdir(parents=True)
    (tmp_path / ".claude" / "skills" / "visible" / "SKILL.md").write_text(
        "---\nname: visible\ndescription: hello\n---\nbody body body\n", encoding="utf-8"
    )
    (tmp_path / ".claude" / "skills" / "hidden").mkdir(parents=True)
    (tmp_path / ".claude" / "skills" / "hidden" / "SKILL.md").write_text(
        "---\nname: hidden\ndescription: secretly long\ndisable-model-invocation: true\n---\n",
        encoding="utf-8",
    )
    (tmp_path / ".claude" / "agents").mkdir(parents=True)
    (tmp_path / ".claude" / "agents" / "a.md").write_text(
        "---\nname: a\ndescription: >\n  one\n  two\n---\nbody\n", encoding="utf-8"
    )

    findings = check_context.run(DoctorContext(root=tmp_path, options={"context": True}))

    sizes = [f for f in findings if f.code == "CONTEXT_SIZE"]
    assert len(sizes) == 1
    # CLAUDE.md 7 文字(あいう\nxy\n) + always.md 4 + skill "hello" 5 + agent "one two" 7
    assert "文字数 23" in sizes[0].message
    # バイト: 3*3+1+2+1=13 + 4 + 5 + 7
    assert "バイト 29" in sizes[0].message
    # 行: 2 + 1 + 1 (description 1行) + 3 (description: > + 2 行)
    assert "行 7" in sizes[0].message
    assert [f.code for f in findings] == ["CONTEXT_SIZE"]


def test_antigravity_always_on_rules_are_counted_and_others_are_not(tmp_path: Path) -> None:
    (tmp_path / ".agents" / "rules").mkdir(parents=True)
    (tmp_path / ".agents" / "rules" / "on.md").write_text(
        "---\ntrigger: always_on\n---\nab\n", encoding="utf-8"
    )
    (tmp_path / ".agents" / "rules" / "glob.md").write_text(
        "---\ntrigger: glob\n---\nxxxxxxxxxx\n", encoding="utf-8"
    )

    findings = check_context.run(DoctorContext(root=tmp_path, options={"context": True}))

    assert "文字数 " + str(len("---\ntrigger: always_on\n---\nab\n")) in findings[0].message


def test_total_above_v1_baseline_warns(tmp_path: Path) -> None:
    (tmp_path / "CLAUDE.md").write_text("あ" * (check_context.V1_BASELINE_CHARS + 1), "utf-8")

    findings = check_context.run(DoctorContext(root=tmp_path, options={"context": True}))

    assert [(f.level, f.code) for f in findings] == [
        (DiagnosticLevel.INFO, "CONTEXT_SIZE"),
        (DiagnosticLevel.WARN, "CONTEXT_ABOVE_V1_BASELINE"),
    ]


def test_v1_baseline_constants_match_baseline_document() -> None:
    assert (
        check_context.V1_BASELINE_CHARS,
        check_context.V1_BASELINE_BYTES,
        check_context.V1_BASELINE_LINES,
    ) == (14835, 30135, 503)
