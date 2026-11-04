from pathlib import Path

from seh.init.detect import ci_check_cmd, ci_fix_cmd, detect


def test_detect_python_uv_project_selects_only_configured_tools(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "demo"\nversion = "0.1"\n'
        '[dependency-groups]\ndev = ["pytest>=8", "pyright>=1.1", "ruff>=0.8"]\n'
        "[tool.ruff]\nline-length = 100\n"
        "[tool.pyright]\ninclude = ['src']\n"
        "[tool.pytest.ini_options]\ntestpaths = ['tests']\n"
    )
    (tmp_path / "uv.lock").write_text("version = 1\n")

    result = detect(tmp_path)

    assert len(result.root_apps) == 1
    app = result.root_apps[0]
    assert app.path == "."
    assert app.languages == ("python",)
    assert app.package_manager == "uv"
    assert ci_check_cmd(app) == (
        "uv run ruff check . && uv run ruff format --check . && uv run pyright && uv run pytest"
    )
    assert ci_fix_cmd(app) == "uv run ruff check --fix . && uv run ruff format ."


def test_detect_python_without_declared_tools_does_not_guess_commands(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "bare"\nversion = "0.1"\n')

    result = detect(tmp_path)

    app = result.root_apps[0]
    assert app.commands.lint is None
    assert app.commands.typecheck is None
    assert app.commands.test is None
    assert ci_check_cmd(app) is None
    assert ci_fix_cmd(app) is None


def test_detect_node_pnpm_without_format_script_leaves_format_none(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text(
        '{"name": "web", "scripts": {"lint": "eslint .", "test": "vitest", '
        '"typecheck": "tsc --noEmit"}}'
    )
    (tmp_path / "pnpm-lock.yaml").write_text("lockfileVersion: 9\n")

    result = detect(tmp_path)

    app = result.root_apps[0]
    assert app.languages == ("node",)
    assert app.package_manager == "pnpm"
    assert app.task_runner == "npm-scripts"
    assert app.commands.format_check is None
    assert app.commands.format_fix is None
    assert ci_check_cmd(app) == "pnpm lint && pnpm typecheck && pnpm test"


def test_detect_node_npm_with_tsconfig_reports_typescript_and_npm_run(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text(
        '{"scripts": {"test": "jest", "format:check": "prettier --check ."}}'
    )
    (tmp_path / "tsconfig.json").write_text("{}")
    (tmp_path / "package-lock.json").write_text("{}")

    app = detect(tmp_path).root_apps[0]

    assert app.languages == ("node", "typescript")
    assert app.package_manager == "npm"
    assert ci_check_cmd(app) == "npm run format:check && npm run test"


def test_detect_go_module_uses_go_toolchain_commands(tmp_path: Path) -> None:
    (tmp_path / "go.mod").write_text("module example.com/demo\n\ngo 1.22\n")

    app = detect(tmp_path).root_apps[0]

    assert app.languages == ("go",)
    assert app.package_manager == "go"
    assert app.commands.lint == "go vet ./..."
    assert app.commands.test == "go test ./..."
    assert app.commands.build == "go build ./..."
    assert ci_fix_cmd(app) == "gofmt -w ."


def test_detect_go_with_golangci_config_prefers_golangci_lint(tmp_path: Path) -> None:
    (tmp_path / "go.mod").write_text("module example.com/demo\n")
    (tmp_path / ".golangci.yml").write_text("linters: {}\n")

    result = detect(tmp_path)

    app = result.root_apps[0]
    assert app.commands.lint == "golangci-lint run"
    assert app.protected_configs == (".golangci.yml",)


def test_detect_rust_cargo_project_uses_cargo_commands(tmp_path: Path) -> None:
    (tmp_path / "Cargo.toml").write_text('[package]\nname = "demo"\nversion = "0.1.0"\n')

    app = detect(tmp_path).root_apps[0]

    assert app.languages == ("rust",)
    assert app.package_manager == "cargo"
    assert ci_check_cmd(app) == (
        "cargo clippy -- -D warnings && cargo fmt --check && cargo check && cargo test"
        " && cargo build"
    )
    assert ci_fix_cmd(app) == "cargo fmt"


def test_detect_makefile_uses_only_existing_targets(tmp_path: Path) -> None:
    (tmp_path / "Makefile").write_text(
        ".PHONY: test lint\nVERSION := 1\n\ntest:\n\tpytest\n\nlint:\n\truff check .\n\n"
        "install:\n\tpip install -e .\n"
    )
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "x"\nversion = "0"\n')

    app = detect(tmp_path).root_apps[0]

    assert app.task_runner == "make"
    assert ci_check_cmd(app) == "make lint && make test"
    assert app.commands.typecheck is None


def test_detect_justfile_recipes_become_commands(tmp_path: Path) -> None:
    (tmp_path / "justfile").write_text(
        "set shell := ['bash', '-c']\n\ntest:\n    cargo test\n\n"
        "fmt-check:\n    cargo fmt --check\n\nfmt:\n    cargo fmt\n"
    )
    (tmp_path / "Cargo.toml").write_text('[package]\nname = "x"\nversion = "0"\n')

    app = detect(tmp_path).root_apps[0]

    assert app.task_runner == "just"
    assert ci_check_cmd(app) == "just fmt-check && just test"
    assert ci_fix_cmd(app) == "just fmt"


def test_detect_moon_wins_over_just_and_make(tmp_path: Path) -> None:
    (tmp_path / ".moon").mkdir()
    (tmp_path / ".moon" / "tasks.yml").write_text("tasks:\n  test:\n    command: pytest\n")
    (tmp_path / "moon.yml").write_text("tasks:\n  lint:\n    command: ruff check .\n")
    (tmp_path / "justfile").write_text("test:\n    pytest\n")
    (tmp_path / "Makefile").write_text("test:\n\tpytest\n")
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "x"\nversion = "0"\n')

    app = detect(tmp_path).root_apps[0]

    assert app.task_runner == "moon"
    assert ci_check_cmd(app) == "moon run :lint && moon run :test"


def test_detect_pnpm_workspace_returns_one_app_per_member(tmp_path: Path) -> None:
    (tmp_path / "pnpm-workspace.yaml").write_text("packages:\n  - 'apps/*'\n")
    (tmp_path / "package.json").write_text('{"name": "root", "private": true}')
    (tmp_path / "apps" / "web").mkdir(parents=True)
    (tmp_path / "apps" / "web" / "package.json").write_text('{"scripts": {"test": "vitest"}}')
    (tmp_path / "apps" / "api").mkdir(parents=True)
    (tmp_path / "apps" / "api" / "package.json").write_text('{"scripts": {"lint": "eslint ."}}')
    (tmp_path / "pnpm-lock.yaml").write_text("lockfileVersion: 9\n")

    result = detect(tmp_path)

    assert [app.path for app in result.root_apps] == ["apps/api", "apps/web"]
    assert ci_check_cmd(result.root_apps[0]) == "pnpm lint"
    assert ci_check_cmd(result.root_apps[1]) == "pnpm test"


def test_detect_conventional_services_dir_without_workspace_file_finds_members(
    tmp_path: Path,
) -> None:
    (tmp_path / "services" / "billing").mkdir(parents=True)
    (tmp_path / "services" / "billing" / "go.mod").write_text("module billing\n")
    (tmp_path / "services" / "notes").mkdir(parents=True)
    (tmp_path / "services" / "notes" / "README.md").write_text("no manifest")

    result = detect(tmp_path)

    assert [app.path for app in result.root_apps] == ["services/billing"]


def test_detect_protected_configs_lists_only_existing_files(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text('{"scripts": {}}')
    (tmp_path / "eslint.config.js").write_text("export default []\n")
    (tmp_path / ".prettierrc.json").write_text("{}")
    (tmp_path / "tsconfig.build.json").write_text("{}")
    (tmp_path / ".editorconfig").write_text("root = true\n")

    app = detect(tmp_path).root_apps[0]

    assert app.protected_configs == (
        ".editorconfig",
        ".prettierrc.json",
        "eslint.config.js",
        "tsconfig.build.json",
    )


def test_detect_existing_harness_reports_assets_and_symlinks(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "x"\nversion = "0"\n')
    (tmp_path / "CLAUDE.md").write_text("# rules\n")
    (tmp_path / ".claude" / "skills").mkdir(parents=True)
    (tmp_path / ".agents").mkdir()
    (tmp_path / ".agents" / "skills").symlink_to("../.claude/skills")
    (tmp_path / ".github" / "workflows").mkdir(parents=True)
    (tmp_path / ".github" / "workflows" / "ci.yml").write_text("on: push\n")

    result = detect(tmp_path)

    assert ".claude" in result.existing_harness
    assert "CLAUDE.md" in result.existing_harness
    assert ".agents" in result.existing_harness
    assert ".agents/skills" in result.existing_harness
    assert "AGENTS.md" not in result.existing_harness
    assert result.existing_symlinks == (".agents/skills",)
    assert result.ci_files == (".github/workflows/ci.yml",)


def test_detect_unreadable_manifest_records_note_and_continues(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("this is = = not toml [")
    (tmp_path / "go.mod").write_text("module demo\n")

    result = detect(tmp_path)

    assert any("pyproject.toml" in note for note in result.notes)
    assert result.root_apps[0].languages == ("python", "go")
