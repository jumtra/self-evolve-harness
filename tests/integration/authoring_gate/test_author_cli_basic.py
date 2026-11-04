import json
import subprocess
from pathlib import Path

import pytest

from seh.cli import main


@pytest.mark.parametrize(
    "argv",
    [
        ["author", "inspect", "--path", ".claude/skills/work/SKILL.md"],
        [
            "author",
            "plan",
            "--target",
            ".claude/skills/work/SKILL.md",
            "--goal",
            "g",
            "--inputs",
            "i",
            "--boundaries",
            "b",
            "--output",
            "o",
            "--feedback",
            "f",
        ],
        ["author", "lint", "--changed"],
        ["author", "eval", "--record", "x.json"],
        ["author", "compare", "--baseline", "a", "--candidate", "b"],
        ["author", "promote", "--record", "x.json"],
        ["author", "rollback", "--promotion", "p"],
    ],
)
def test_every_subcommand_reports_not_configured_and_exits_zero(
    argv: list[str], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main([*argv, "--root", str(tmp_path)])

    assert code == 0
    assert "NOT_CONFIGURED" in capsys.readouterr().out


def test_plan_creates_planned_record_for_behavioral_target(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / ".harness").mkdir()
    (tmp_path / ".harness" / "config.toml").write_text('profile = "balanced"\n')
    skill = tmp_path / ".claude" / "skills" / "work" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("---\nname: work\ndescription: 開発依頼で使う\n---\n本文\n")

    code = main(
        [
            "author",
            "plan",
            "--root",
            str(tmp_path),
            "--target",
            ".claude/skills/work/SKILL.md",
            "--goal",
            "description を短くする",
            "--inputs",
            "現行 SKILL.md",
            "--boundaries",
            "本文は変えない",
            "--output",
            "更新済み SKILL.md",
            "--feedback",
            "trigger eval",
            "--id",
            "AUTH-T1",
        ]
    )

    saved = json.loads((tmp_path / ".harness/authoring/AUTH-T1.json").read_text())
    assert code == 0
    assert saved["state"] == "PLANNED"
    assert saved["risk"] == "behavioral"
    assert saved["target_paths"] == [".claude/skills/work/SKILL.md"]
    assert saved["spec"]["goal"] == "description を短くする"
    assert "file:.claude/skills/work/SKILL.md" in saved["exploration"]["evidence_refs"]
    assert "AUTH-T1" in capsys.readouterr().out


def test_plan_for_permission_config_awaits_approval(tmp_path: Path) -> None:
    (tmp_path / ".harness").mkdir()
    (tmp_path / ".harness" / "config.toml").write_text('profile = "balanced"\n')
    settings = tmp_path / ".claude" / "settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text('{"permissions": {"allow": ["Bash(*)"]}}')

    code = main(
        [
            "author",
            "plan",
            "--root",
            str(tmp_path),
            "--target",
            ".claude/settings.json",
            "--goal",
            "g",
            "--inputs",
            "i",
            "--boundaries",
            "b",
            "--output",
            "o",
            "--feedback",
            "f",
            "--id",
            "AUTH-T2",
        ]
    )

    saved = json.loads((tmp_path / ".harness/authoring/AUTH-T2.json").read_text())
    assert code == 0
    assert (saved["risk"], saved["state"]) == ("high_risk", "AWAITING_APPROVAL")


def test_plan_rejects_non_authoring_target_and_unsafe_id(tmp_path: Path) -> None:
    (tmp_path / ".harness").mkdir()
    (tmp_path / ".harness" / "config.toml").write_text('profile = "balanced"\n')
    common = ["--goal", "g", "--inputs", "i", "--boundaries", "b", "--output", "o"]

    not_authoring = main(
        ["author", "plan", "--root", str(tmp_path), "--target", "src/app.py", *common]
        + ["--feedback", "f"]
    )
    unsafe_id = main(
        ["author", "plan", "--root", str(tmp_path), "--target", "CLAUDE.md", *common]
        + ["--feedback", "f", "--id", "../evil"]
    )

    assert (not_authoring, unsafe_id) == (1, 1)
    assert not (tmp_path / ".harness" / "authoring").exists()


def test_inspect_prints_classification(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / ".harness").mkdir()
    (tmp_path / ".harness" / "config.toml").write_text('profile = "balanced"\n')
    (tmp_path / "CLAUDE.md").write_text("# 指示\n")

    code = main(["author", "inspect", "--root", str(tmp_path), "--path", "CLAUDE.md"])

    out = capsys.readouterr().out
    assert code == 0
    assert "kind: instructions" in out
    assert "risk: high_risk" in out


def test_lint_changed_flags_edit_made_outside_hooks_as_unreviewed_a06(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scenario = json.loads(
        Path("tests/fixtures/prompt_skill/authoring/A06.json").read_text(encoding="utf-8")
    )
    changed = scenario["input"]["changed_files"][0]
    monkeypatch.delenv("CI", raising=False)
    (tmp_path / ".harness").mkdir()
    (tmp_path / ".harness" / "config.toml").write_text('profile = "balanced"\n')
    skill = tmp_path / changed
    skill.parent.mkdir(parents=True)
    skill.write_text("---\nname: work\ndescription: 開発依頼で使う\n---\n" + "手順A\n" * 30)
    git = ["git", "-C", str(tmp_path), "-c", "user.name=t", "-c", "user.email=t@example.invalid"]
    subprocess.run([*git, "init", "-q"], check=True)
    subprocess.run([*git, "add", "-A"], check=True)
    subprocess.run([*git, "commit", "-q", "-m", "base"], check=True)
    skill.write_text("---\nname: work\ndescription: 開発依頼で使う\n---\n" + "全く別の手順B\n" * 30)

    code = main(["author", "lint", "--root", str(tmp_path), "--changed", "--base", "HEAD"])

    out = capsys.readouterr().out
    assert scenario["expected"]["state"] == "REJECTED_UNEVALUATED_CHANGE"
    assert code == 1
    assert f"UNREVIEWED_AUTHORING_CHANGE:{changed}" in out
    assert "強制力: NOT_ENFORCED（GitHub 必須チェック未設定。CI で可視化のみ）" in out


def test_lint_changed_json_and_ci_env_hides_not_enforced_notice(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CI", "true")
    (tmp_path / ".harness").mkdir()
    (tmp_path / ".harness" / "config.toml").write_text('profile = "balanced"\n')
    skill = tmp_path / ".claude" / "skills" / "work" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("---\nname: work\ndescription: d\n---\n" + "手順A\n" * 30)
    git = ["git", "-C", str(tmp_path), "-c", "user.name=t", "-c", "user.email=t@example.invalid"]
    subprocess.run([*git, "init", "-q"], check=True)
    subprocess.run([*git, "add", "-A"], check=True)
    subprocess.run([*git, "commit", "-q", "-m", "base"], check=True)
    skill.write_text("---\nname: work\ndescription: d\n---\n" + "別の手順B\n" * 30)

    code = main(
        [
            "author",
            "lint",
            "--root",
            str(tmp_path),
            "--changed",
            "--base",
            "HEAD",
            "--format",
            "json",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert code == 1
    assert payload["enforcement"] is None
    assert payload["diagnostics"][0]["code"].startswith("UNREVIEWED_AUTHORING_CHANGE:")
    assert payload["diagnostics"][0]["level"] == "ERROR"


def test_lint_changed_accepts_change_covered_by_promoted_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("CI", raising=False)
    (tmp_path / ".harness" / "authoring").mkdir(parents=True)
    (tmp_path / ".harness" / "config.toml").write_text('profile = "balanced"\n')
    skill = tmp_path / ".claude" / "skills" / "work" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("---\nname: work\ndescription: d\n---\n" + "手順A\n" * 30)
    git = ["git", "-C", str(tmp_path), "-c", "user.name=t", "-c", "user.email=t@example.invalid"]
    subprocess.run([*git, "init", "-q"], check=True)
    subprocess.run([*git, "add", "-A"], check=True)
    subprocess.run([*git, "commit", "-q", "-m", "base"], check=True)
    skill.write_text("---\nname: work\ndescription: d\n---\n" + "別の手順B\n" * 30)
    (tmp_path / ".harness/authoring/AUTH-P.json").write_text(
        json.dumps(
            {
                "id": "AUTH-P",
                "target_kind": "skill",
                "target_paths": [".claude/skills/work/SKILL.md"],
                "risk": "behavioral",
                "exploration": {"evidence_refs": ["file:.claude/skills/work/SKILL.md"]},
                "spec": {"goal": "g"},
                "state": "PROMOTED",
            }
        )
    )

    code = main(["author", "lint", "--root", str(tmp_path), "--changed", "--base", "HEAD"])

    assert code == 0


def test_lint_reports_spec_errors_from_canonical_source(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / ".harness" / "spec" / "skills" / "work").mkdir(parents=True)
    (tmp_path / ".harness" / "spec" / "instructions").mkdir(parents=True)
    (tmp_path / ".harness" / "config.toml").write_text('profile = "balanced"\n')
    (tmp_path / ".harness" / "spec" / "instructions" / "core.md").write_text("共通方針\n")
    (tmp_path / ".harness" / "spec" / "skills" / "work" / "SKILL.md").write_text(
        "---\ndescription: 開発依頼で使う\n---\n見出しの無い本文\n"
    )

    code = main(["author", "lint", "--root", str(tmp_path)])

    out = capsys.readouterr().out
    assert code == 1
    assert "SKILL_CONTRACT_MISSING:goal" in out
