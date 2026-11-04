import os
from pathlib import Path

import pytest

from seh.config import ConfigError, load_config
from seh.contracts import HostId
from seh.init import planner
from seh.init.planner import InitError, InitOptions, plan_init
from seh.migration import inventory
from seh.migration.inventory import KnownPath


def test_plan_init_leaves_repository_and_home_untouched(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    spec = tmp_path / "spec"
    home = tmp_path / "home"
    (spec / "instructions").mkdir(parents=True)
    (spec / "instructions" / "core.md").write_text("# {{project_name}}\n", encoding="utf-8")
    repo.mkdir()
    home.mkdir()
    (repo / "pyproject.toml").write_text("[tool.ruff]\n", encoding="utf-8")
    (repo / "uv.lock").write_text("", encoding="utf-8")
    (repo / ".gitignore").write_text("*.pyc\n", encoding="utf-8")
    monkeypatch.setenv("HOME", str(home))
    before = {
        str(Path(c, f)): (Path(c, f).stat().st_mtime_ns, Path(c, f).stat().st_size)
        for c, _, files in os.walk(repo)
        for f in files
    }

    plan = plan_init(repo, InitOptions(spec_source=spec))

    assert plan.sync.items
    after = {
        str(Path(c, f)): (Path(c, f).stat().st_mtime_ns, Path(c, f).stat().st_size)
        for c, _, files in os.walk(repo)
        for f in files
    }
    assert after == before
    assert list(home.iterdir()) == []
    assert not (repo / ".harness").exists()


def test_templates_are_rendered_only_for_core_and_rules(tmp_path: Path) -> None:
    repo = tmp_path / "myrepo"
    spec = tmp_path / "spec"
    repo.mkdir()
    (repo / "pyproject.toml").write_text("[tool.ruff]\n", encoding="utf-8")
    (repo / "uv.lock").write_text("", encoding="utf-8")
    (repo / "ruff.toml").write_text("line-length = 100\n", encoding="utf-8")
    (spec / "instructions").mkdir(parents=True)
    (spec / "skills" / "demo").mkdir(parents=True)
    (spec / "rules").mkdir()
    (spec / "instructions" / "core.md").write_text(
        "# {{project_name}}\ncheck: {{ci_check_cmd}}\nfix: {{ci_fix_cmd}}\n{{protected_configs}}\n",
        encoding="utf-8",
    )
    (spec / "rules" / "style.md").write_text(
        "---\ndescription: 規約\nalways: true\n---\nproject={{project_name}}\n", encoding="utf-8"
    )
    (spec / "skills" / "demo" / "SKILL.md").write_text(
        "---\ndescription: 説明\n---\n{{project_name}} は置換しない\n", encoding="utf-8"
    )

    plan = plan_init(repo, InitOptions(spec_source=spec))

    core = plan.spec_files[".harness/spec/instructions/core.md"].decode()
    assert core.startswith("# myrepo\n")
    assert "check: uv run ruff check . && uv run ruff format --check .\n" in core
    assert "fix: uv run ruff check --fix . && uv run ruff format .\n" in core
    assert "- ruff.toml" in core
    rule = plan.spec_files[".harness/spec/rules/style.md"].decode()
    assert "project=myrepo" in rule
    skill = plan.spec_files[".harness/spec/skills/demo/SKILL.md"].decode()
    assert "{{project_name}} は置換しない" in skill


def test_unknown_template_variable_raises_init_error(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    spec = tmp_path / "spec"
    repo.mkdir()
    (spec / "instructions").mkdir(parents=True)
    (spec / "instructions" / "core.md").write_text("{{nope}}\n", encoding="utf-8")

    with pytest.raises(InitError, match="nope"):
        plan_init(repo, InitOptions(spec_source=spec))


def test_already_initialized_repository_raises_init_error(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    spec = tmp_path / "spec"
    (repo / ".harness").mkdir(parents=True)
    (repo / ".harness" / "config.toml").write_text('profile = "balanced"\n', encoding="utf-8")
    (spec / "instructions").mkdir(parents=True)
    (spec / "instructions" / "core.md").write_text("x\n", encoding="utf-8")

    with pytest.raises(InitError, match="既に導入済みです。seh sync を使ってください"):
        plan_init(repo, InitOptions(spec_source=spec))


def test_missing_distributed_template_raises_init_error(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setattr(planner, "template_spec_dir", lambda: None)

    with pytest.raises(InitError, match="配布テンプレートが見つかりません"):
        plan_init(repo, InitOptions())


def test_options_are_reflected_in_config(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    spec = tmp_path / "spec"
    repo.mkdir()
    (spec / "instructions").mkdir(parents=True)
    (spec / "instructions" / "core.md").write_text("x\n", encoding="utf-8")
    options = InitOptions(
        profile="full",
        hosts=(HostId.CLAUDE, HostId.CODEX),
        code_intelligence="codegraph",
        memory="engram",
        spec_source=spec,
    )

    plan = plan_init(repo, options)

    config_path = tmp_path / "config.toml"
    config_path.write_text(plan.config_toml, encoding="utf-8")
    loaded = load_config(config_path)
    assert loaded == plan.config
    assert loaded.profile == "full"
    assert loaded.hosts.enabled == (HostId.CLAUDE, HostId.CODEX)
    assert loaded.code_intelligence.provider == "codegraph"
    assert loaded.memory.provider == "engram"
    assert {h for h in plan.sync.capabilities} == {HostId.CLAUDE, HostId.CODEX}


def test_invalid_provider_raises_config_error(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    spec = tmp_path / "spec"
    repo.mkdir()
    (spec / "instructions").mkdir(parents=True)
    (spec / "instructions" / "core.md").write_text("x\n", encoding="utf-8")

    with pytest.raises(ConfigError):
        plan_init(repo, InitOptions(memory="redis", spec_source=spec))


def test_v1_repository_gets_migration_plan(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    spec = tmp_path / "spec"
    skill = repo / ".claude" / "skills" / "old-skill" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("v1 の内容\n", encoding="utf-8")
    (spec / "instructions").mkdir(parents=True)
    (spec / "instructions" / "core.md").write_text("x\n", encoding="utf-8")
    digest = inventory.fingerprint(repo, ".claude/skills/old-skill/SKILL.md")
    assert digest is not None
    known = {".claude/skills/old-skill/SKILL.md": KnownPath("skill", "DELETE", digest)}
    monkeypatch.setattr(inventory, "load_known_paths", lambda: ("base", known))

    plan = plan_init(repo, InitOptions(spec_source=spec))

    assert plan.migration is not None
    assert [(i.path, i.action.value) for i in plan.migration.items] == [
        (".claude/skills/old-skill/SKILL.md", "DELETE")
    ]


def test_gitignore_block_content(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    spec = tmp_path / "spec"
    repo.mkdir()
    (spec / "instructions").mkdir(parents=True)
    (spec / "instructions" / "core.md").write_text("x\n", encoding="utf-8")

    plan = plan_init(repo, InitOptions(spec_source=spec))

    assert plan.gitignore_block == (
        "# seh:begin\n.harness/state/\n.harness/artifacts/\n.harness/backups/\n# seh:end\n"
    )
    assert plan.migration is None


def test_all_hosts_excludes_antigravity_from_required_hosts(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    spec = tmp_path / "spec"
    repo.mkdir()
    (spec / "instructions").mkdir(parents=True)
    (spec / "instructions" / "core.md").write_text("x\n", encoding="utf-8")

    plan = plan_init(repo, InitOptions(hosts=tuple(HostId), spec_source=spec))

    assert plan.config.hosts.enabled == (
        HostId.CLAUDE,
        HostId.ANTIGRAVITY,
        HostId.CODEX,
        HostId.OPENCODE,
    )
    assert plan.config.authoring.required_hosts == (
        HostId.CLAUDE,
        HostId.CODEX,
        HostId.OPENCODE,
    )
