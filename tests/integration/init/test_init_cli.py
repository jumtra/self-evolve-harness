import io
import json
from pathlib import Path

from seh.cli import main
from seh.commands import init as init_command
from seh.init import planner
from seh.migration import inventory
from seh.migration.inventory import KnownPath


class _Tty(io.StringIO):
    def isatty(self) -> bool:
        return True


def test_plan_prints_summary_and_writes_nothing(tmp_path: Path, capsys, monkeypatch) -> None:
    repo = tmp_path / "repo"
    spec = tmp_path / "spec"
    repo.mkdir()
    (spec / "instructions").mkdir(parents=True)
    (spec / "skills" / "demo").mkdir(parents=True)
    (spec / "instructions" / "core.md").write_text("# {{project_name}}\n", encoding="utf-8")
    (spec / "skills" / "demo" / "SKILL.md").write_text(
        "---\ndescription: 説明\n---\n本文\n", encoding="utf-8"
    )
    monkeypatch.setattr(planner, "template_spec_dir", lambda: spec)
    monkeypatch.setattr(init_command, "_cli_versions", lambda hosts: {})

    code = main(["init", "--root", str(repo), "--plan", "--profile", "minimal"])

    out = capsys.readouterr().out
    assert code == 0
    assert 'profile = "minimal"' in out
    assert ".harness/spec/instructions/core.md" in out
    assert ".claude/skills/demo/SKILL.md" in out
    assert list(repo.iterdir()) == []


def test_plan_json_output_is_parseable(tmp_path: Path, capsys, monkeypatch) -> None:
    repo = tmp_path / "repo"
    spec = tmp_path / "spec"
    repo.mkdir()
    (spec / "instructions").mkdir(parents=True)
    (spec / "skills" / "demo").mkdir(parents=True)
    (spec / "instructions" / "core.md").write_text("# {{project_name}}\n", encoding="utf-8")
    (spec / "skills" / "demo" / "SKILL.md").write_text(
        "---\ndescription: 説明\n---\n本文\n", encoding="utf-8"
    )
    monkeypatch.setattr(planner, "template_spec_dir", lambda: spec)
    monkeypatch.setattr(init_command, "_cli_versions", lambda hosts: {})

    code = main(["init", "--root", str(repo), "--plan", "--format", "json", "--hosts", "all"])

    data = json.loads(capsys.readouterr().out)
    assert code == 0
    assert ".harness/spec/instructions/core.md" in data["spec_files"]
    assert {i["path"] for i in data["sync"]["items"]} >= {"AGENTS.md", "CLAUDE.md"}


def test_plan_on_initialized_repo_exits_1(tmp_path: Path, capsys, monkeypatch) -> None:
    repo = tmp_path / "repo"
    spec = tmp_path / "spec"
    repo.mkdir()
    (spec / "instructions").mkdir(parents=True)
    (spec / "skills" / "demo").mkdir(parents=True)
    (spec / "instructions" / "core.md").write_text("# {{project_name}}\n", encoding="utf-8")
    (spec / "skills" / "demo" / "SKILL.md").write_text(
        "---\ndescription: 説明\n---\n本文\n", encoding="utf-8"
    )
    monkeypatch.setattr(planner, "template_spec_dir", lambda: spec)
    monkeypatch.setattr(init_command, "_cli_versions", lambda hosts: {})
    (repo / ".harness").mkdir()
    (repo / ".harness" / "config.toml").write_text('profile = "balanced"\n', encoding="utf-8")

    code = main(["init", "--root", str(repo), "--plan"])

    assert code == 1
    assert "既に導入済みです" in capsys.readouterr().err


def test_apply_without_tty_is_refused_and_writes_nothing(
    tmp_path: Path, capsys, monkeypatch
) -> None:
    repo = tmp_path / "repo"
    spec = tmp_path / "spec"
    repo.mkdir()
    (spec / "instructions").mkdir(parents=True)
    (spec / "skills" / "demo").mkdir(parents=True)
    (spec / "instructions" / "core.md").write_text("# {{project_name}}\n", encoding="utf-8")
    (spec / "skills" / "demo" / "SKILL.md").write_text(
        "---\ndescription: 説明\n---\n本文\n", encoding="utf-8"
    )
    monkeypatch.setattr(planner, "template_spec_dir", lambda: spec)
    monkeypatch.setattr(init_command, "_cli_versions", lambda hosts: {})

    code = main(["init", "--root", str(repo), "--apply"])

    assert code == 1
    assert "承認が必要です。対話モードで再実行してください" in capsys.readouterr().err
    assert list(repo.iterdir()) == []


def test_apply_with_tty_confirmation_installs_harness(tmp_path: Path, capsys, monkeypatch) -> None:
    repo = tmp_path / "repo"
    spec = tmp_path / "spec"
    repo.mkdir()
    (spec / "instructions").mkdir(parents=True)
    (spec / "skills" / "demo").mkdir(parents=True)
    (spec / "instructions" / "core.md").write_text("# {{project_name}}\n", encoding="utf-8")
    (spec / "skills" / "demo" / "SKILL.md").write_text(
        "---\ndescription: 説明\n---\n本文\n", encoding="utf-8"
    )
    monkeypatch.setattr(planner, "template_spec_dir", lambda: spec)
    monkeypatch.setattr(init_command, "_cli_versions", lambda hosts: {})
    monkeypatch.setattr("sys.stdin", _Tty(""))
    monkeypatch.setattr("builtins.input", lambda prompt="": "y")

    code = main(["init", "--root", str(repo), "--apply"])

    out = capsys.readouterr().out
    assert code == 0
    assert (repo / ".harness/config.toml").is_file()
    assert (repo / ".claude/skills/demo/SKILL.md").is_file()
    assert "doctor" in out
    assert "v1 移行はありませんでした" in out


def test_apply_declined_writes_nothing(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    spec = tmp_path / "spec"
    repo.mkdir()
    (spec / "instructions").mkdir(parents=True)
    (spec / "skills" / "demo").mkdir(parents=True)
    (spec / "instructions" / "core.md").write_text("# {{project_name}}\n", encoding="utf-8")
    (spec / "skills" / "demo" / "SKILL.md").write_text(
        "---\ndescription: 説明\n---\n本文\n", encoding="utf-8"
    )
    monkeypatch.setattr(planner, "template_spec_dir", lambda: spec)
    monkeypatch.setattr(init_command, "_cli_versions", lambda hosts: {})
    monkeypatch.setattr("sys.stdin", _Tty(""))
    monkeypatch.setattr("builtins.input", lambda prompt="": "n")

    code = main(["init", "--root", str(repo), "--apply"])

    assert code == 1
    assert list(repo.iterdir()) == []


def test_apply_of_v1_repo_prints_migration_rollback_command(
    tmp_path: Path, capsys, monkeypatch
) -> None:
    repo = tmp_path / "repo"
    spec = tmp_path / "spec"
    old = repo / ".claude/skills/old-skill/SKILL.md"
    old.parent.mkdir(parents=True)
    old.write_text("v1\n", encoding="utf-8")
    (spec / "instructions").mkdir(parents=True)
    (spec / "instructions" / "core.md").write_text("x\n", encoding="utf-8")
    digest = inventory.fingerprint(repo, ".claude/skills/old-skill/SKILL.md")
    assert digest is not None
    known = {".claude/skills/old-skill/SKILL.md": KnownPath("skill", "DELETE", digest)}
    monkeypatch.setattr(inventory, "load_known_paths", lambda: ("base", known))
    monkeypatch.setattr(planner, "template_spec_dir", lambda: spec)
    monkeypatch.setattr(init_command, "_cli_versions", lambda hosts: {})
    monkeypatch.setattr("sys.stdin", _Tty(""))
    monkeypatch.setattr("builtins.input", lambda prompt="": "y")

    code = main(["init", "--root", str(repo), "--apply"])

    assert code == 0
    assert not old.exists()
    assert "seh migrate rollback" in capsys.readouterr().out
