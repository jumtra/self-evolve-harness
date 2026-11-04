from __future__ import annotations

import io
import json
import shutil
from pathlib import Path

import pytest

from seh.cli import main
from seh.commands import init as init_command
from seh.migration import inventory
from seh.migration.inventory import KnownPath


@pytest.mark.parametrize(("sample", "language"), [("python", "python"), ("typescript", "node")])
def test_fresh_sample_plan_and_apply_support_four_hosts(
    sample: str,
    language: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo = tmp_path / "repo"
    shutil.copytree(Path("tests/fixtures/samples") / sample, repo)
    before = sorted(str(p.relative_to(repo)) for p in repo.rglob("*") if p.is_file())
    monkeypatch.setattr(init_command, "_cli_versions", lambda hosts: {})
    code = main(["init", "--root", str(repo), "--hosts", "all", "--plan", "--format", "json"])
    data = json.loads(capsys.readouterr().out)
    assert code == 0
    assert language in data["detection"]["root_apps"][0]["languages"]
    assert sorted(str(p.relative_to(repo)) for p in repo.rglob("*") if p.is_file()) == before
    stdin = io.StringIO()
    monkeypatch.setattr(stdin, "isatty", lambda: True)
    monkeypatch.setattr("sys.stdin", stdin)
    monkeypatch.setattr("builtins.input", lambda prompt="": "y")
    code = main(["init", "--root", str(repo), "--hosts", "all", "--apply"])
    assert code == 0
    assert (repo / ".harness/config.toml").is_file()
    assert (repo / "CLAUDE.md").is_file()
    assert (repo / "AGENTS.md").is_file()
    assert (repo / ".agents/skills/work/SKILL.md").is_file()
    assert (repo / ".agents/agents/implementer.md").is_file()
    assert (repo / ".codex/agents/implementer.toml").is_file()
    assert (repo / ".opencode/agents/implementer.md").is_file()
    capsys.readouterr()
    code = main(["sync", "--root", str(repo), "--hosts", "all", "--plan", "--format", "json"])
    sync_plan = json.loads(capsys.readouterr().out)
    assert code == 0
    assert sync_plan["conflicts"] == []
    assert set(sync_plan["collisions"]) == {
        "DISCOVERY_COLLISION:opencode:harness-init",
        "DISCOVERY_COLLISION:opencode:work",
    }
    assert {item["status"] for item in sync_plan["items"]} == {"UNCHANGED"}


def test_unattended_init_is_refused_without_modifying_sample(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo = tmp_path / "repo"
    shutil.copytree(Path("tests/fixtures/samples/python"), repo)
    before = sorted(str(p.relative_to(repo)) for p in repo.rglob("*") if p.is_file())
    monkeypatch.setattr(init_command, "_cli_versions", lambda hosts: {})
    monkeypatch.setattr("sys.stdin", io.StringIO("y\n"))
    code = main(["init", "--root", str(repo), "--apply"])
    assert code == 1
    assert "承認が必要" in capsys.readouterr().err
    assert sorted(str(p.relative_to(repo)) for p in repo.rglob("*") if p.is_file()) == before


def test_v1_migration_apply_and_rollback_restore_original(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo = tmp_path / "repo"
    shutil.copytree(Path("tests/fixtures/samples/python"), repo)
    old = repo / ".claude/skills/legacy/SKILL.md"
    old.parent.mkdir(parents=True)
    old.write_text("legacy content\n")
    digest = inventory.fingerprint(repo, ".claude/skills/legacy/SKILL.md")
    assert digest is not None
    monkeypatch.setattr(
        inventory,
        "load_known_paths",
        lambda: (
            "base",
            {
                ".claude/skills/legacy/SKILL.md": KnownPath("skill", "DELETE", digest),
            },
        ),
    )
    assert main(["migrate", "plan", "--root", str(repo)]) == 0
    output = capsys.readouterr().out
    plan_path = Path(output.split("計画を保存しました: ", 1)[1].strip())
    stdin = io.StringIO("y\n")
    monkeypatch.setattr(stdin, "isatty", lambda: True)
    monkeypatch.setattr("sys.stdin", stdin)
    assert main(["migrate", "apply", "--root", str(repo), "--plan", str(plan_path)]) == 0
    output = capsys.readouterr().out
    snapshot = output.split("snapshot: ", 1)[1].splitlines()[0]
    assert not old.exists()
    assert main(["migrate", "rollback", snapshot, "--root", str(repo)]) == 0
    assert old.read_text() == "legacy content\n"


def test_authoring_promotion_without_evidence_is_refused(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo = tmp_path / "repo"
    shutil.copytree(Path("tests/fixtures/samples/python"), repo)
    (repo / ".harness").mkdir()
    (repo / ".harness/config.toml").write_text('profile = "balanced"\n')
    skill = repo / ".claude/skills/work/SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("---\nname: work\ndescription: 依頼で利用\n---\n本文\n")
    code = main(
        [
            "author",
            "plan",
            "--root",
            str(repo),
            "--target",
            ".claude/skills/work/SKILL.md",
            "--goal",
            "説明を変更",
            "--inputs",
            "現行の説明",
            "--boundaries",
            "本文を維持",
            "--output",
            "説明",
            "--feedback",
            "評価結果",
            "--id",
            "AUTH-T64",
        ]
    )
    assert code == 0
    record = repo / ".harness/authoring/AUTH-T64.json"
    code = main(["author", "promote", "--root", str(repo), "--record", str(record)])
    assert code != 0
    assert skill.read_text() == "---\nname: work\ndescription: 依頼で利用\n---\n本文\n"
