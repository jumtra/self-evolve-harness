import json
import subprocess
from pathlib import Path

import pytest

from seh.cli import main
from seh.contracts import HostId
from seh.init.apply import apply_init
from seh.init.planner import InitOptions, plan_init
from seh.spec_loader import load_spec
from seh.sync import apply_sync, plan_sync

CONTRACT = "## Goal\na\n## Inputs\nb\n## Boundaries\nc\n## Output\nd\n## Feedback\ne\n"
SKILL = "---\ndescription: 開発依頼で使う\n---\n" + CONTRACT
SKILL_EDITED = SKILL + "新しい手順を追加する。\n" * 10


def test_lint_changed_untouched_initial_spec_and_generated_files_are_not_flagged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("CI", raising=False)
    repo = tmp_path / "repo"
    source = tmp_path / "spec"
    repo.mkdir()
    (repo / "README.md").write_text("r\n")
    (source / "instructions").mkdir(parents=True)
    (source / "skills" / "demo").mkdir(parents=True)
    (source / "instructions" / "core.md").write_text("共通方針\n")
    (source / "skills" / "demo" / "SKILL.md").write_text(SKILL)
    git = ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@example.invalid"]
    subprocess.run([*git, "init", "-q"], check=True)
    subprocess.run([*git, "add", "-A"], check=True)
    subprocess.run([*git, "commit", "-q", "-m", "base"], check=True)
    plan = plan_init(repo, InitOptions(hosts=(HostId.CLAUDE,), spec_source=source))
    apply_init(repo, plan, seh_version="2.0.0", cli_versions={})

    code = main(["author", "lint", "--root", str(repo), "--changed", "--base", "HEAD"])

    out = capsys.readouterr().out
    assert code == 0, out
    assert "UNREVIEWED_AUTHORING_CHANGE" not in out
    assert "GENERATED_FILE_DRIFT" not in out


def test_lint_changed_edited_spec_after_init_is_unreviewed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("CI", raising=False)
    repo = tmp_path / "repo"
    source = tmp_path / "spec"
    repo.mkdir()
    (repo / "README.md").write_text("r\n")
    (source / "instructions").mkdir(parents=True)
    (source / "skills" / "demo").mkdir(parents=True)
    (source / "instructions" / "core.md").write_text("共通方針\n")
    (source / "skills" / "demo" / "SKILL.md").write_text(SKILL)
    git = ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@example.invalid"]
    subprocess.run([*git, "init", "-q"], check=True)
    subprocess.run([*git, "add", "-A"], check=True)
    subprocess.run([*git, "commit", "-q", "-m", "base"], check=True)
    plan = plan_init(repo, InitOptions(hosts=(HostId.CLAUDE,), spec_source=source))
    apply_init(repo, plan, seh_version="2.0.0", cli_versions={})
    (repo / ".harness/spec/skills/demo/SKILL.md").write_text(SKILL_EDITED)

    code = main(["author", "lint", "--root", str(repo), "--changed", "--base", "HEAD"])

    out = capsys.readouterr().out
    assert code == 1
    assert "UNREVIEWED_AUTHORING_CHANGE:.harness/spec/skills/demo/SKILL.md" in out


def test_lint_changed_generated_files_synced_from_reviewed_spec_are_accepted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("CI", raising=False)
    repo = tmp_path / "repo"
    source = tmp_path / "spec"
    repo.mkdir()
    (repo / "README.md").write_text("r\n")
    (source / "instructions").mkdir(parents=True)
    (source / "skills" / "demo").mkdir(parents=True)
    (source / "instructions" / "core.md").write_text("共通方針\n")
    (source / "skills" / "demo" / "SKILL.md").write_text(SKILL)
    plan = plan_init(repo, InitOptions(hosts=(HostId.CLAUDE,), spec_source=source))
    apply_init(repo, plan, seh_version="2.0.0", cli_versions={})
    (repo / ".gitignore").write_text(".harness/backups/\n")
    git = ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@example.invalid"]
    subprocess.run([*git, "init", "-q"], check=True)
    subprocess.run([*git, "add", "-A"], check=True)
    subprocess.run([*git, "commit", "-q", "-m", "base"], check=True)
    (repo / ".harness/spec/skills/demo/SKILL.md").write_text(SKILL_EDITED)
    resync = plan_sync(repo, [HostId.CLAUDE], spec=load_spec(repo / ".harness" / "spec"))
    apply_sync(repo, resync, seh_version="2.0.0", cli_versions={})
    (repo / ".harness" / "authoring").mkdir(parents=True, exist_ok=True)
    (repo / ".harness/authoring/AUTH-S.json").write_text(
        json.dumps(
            {
                "id": "AUTH-S",
                "target_kind": "skill",
                "target_paths": [".harness/spec/skills/demo/SKILL.md"],
                "risk": "behavioral",
                "exploration": {"evidence_refs": ["file:.claude/skills/demo/SKILL.md"]},
                "spec": {"goal": "g"},
                "state": "PROMOTED",
            }
        )
    )

    code = main(["author", "lint", "--root", str(repo), "--changed", "--base", "HEAD"])

    out = capsys.readouterr().out
    assert code == 0, out
    assert "GENERATED_FILE_DRIFT" not in out


def test_lint_changed_hand_edited_generated_skill_is_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("CI", raising=False)
    repo = tmp_path / "repo"
    source = tmp_path / "spec"
    repo.mkdir()
    (repo / "README.md").write_text("r\n")
    (source / "instructions").mkdir(parents=True)
    (source / "skills" / "demo").mkdir(parents=True)
    (source / "instructions" / "core.md").write_text("共通方針\n")
    (source / "skills" / "demo" / "SKILL.md").write_text(SKILL)
    git = ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@example.invalid"]
    subprocess.run([*git, "init", "-q"], check=True)
    subprocess.run([*git, "add", "-A"], check=True)
    subprocess.run([*git, "commit", "-q", "-m", "base"], check=True)
    plan = plan_init(repo, InitOptions(hosts=(HostId.CLAUDE,), spec_source=source))
    apply_init(repo, plan, seh_version="2.0.0", cli_versions={})
    generated = repo / ".claude/skills/demo/SKILL.md"
    generated.write_text(generated.read_text() + "直接編集した行\n")

    code = main(["author", "lint", "--root", str(repo), "--changed", "--base", "HEAD"])

    out = capsys.readouterr().out
    assert code == 1
    assert "GENERATED_FILE_DRIFT:.claude/skills/demo/SKILL.md" in out


def test_lint_changed_user_text_outside_managed_block_of_claude_md_is_ignored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("CI", raising=False)
    repo = tmp_path / "repo"
    source = tmp_path / "spec"
    repo.mkdir()
    (repo / "README.md").write_text("r\n")
    (source / "instructions").mkdir(parents=True)
    (source / "instructions" / "core.md").write_text("共通方針\n")
    git = ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@example.invalid"]
    subprocess.run([*git, "init", "-q"], check=True)
    subprocess.run([*git, "add", "-A"], check=True)
    subprocess.run([*git, "commit", "-q", "-m", "base"], check=True)
    plan = plan_init(repo, InitOptions(hosts=(HostId.CLAUDE,), spec_source=source))
    apply_init(repo, plan, seh_version="2.0.0", cli_versions={})
    claude_md = repo / "CLAUDE.md"
    claude_md.write_text(claude_md.read_text() + "\n# 自分用のメモ\nここは手書き\n")

    code = main(["author", "lint", "--root", str(repo), "--changed", "--base", "HEAD"])

    out = capsys.readouterr().out
    assert code == 0, out
    assert "GENERATED_FILE_DRIFT:CLAUDE.md" not in out
