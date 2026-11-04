from pathlib import Path

import pytest

from seh.init.detect import ci_check_cmd, detect


def test_detect_does_not_modify_repo_or_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "repo"
    home = tmp_path / "home"
    (repo / "apps" / "web").mkdir(parents=True)
    home.mkdir()
    (repo / "pyproject.toml").write_text("[tool.ruff]\nline-length = 100\n")
    (repo / "apps" / "web" / "package.json").write_text('{"scripts": {"test": "vitest"}}')
    (repo / ".claude").mkdir()
    (repo / ".claude" / "settings.json").write_text("{}")
    monkeypatch.setenv("HOME", str(home))
    before = sorted((str(p), p.lstat().st_mtime_ns, p.lstat().st_size) for p in tmp_path.rglob("*"))

    detect(repo)

    after = sorted((str(p), p.lstat().st_mtime_ns, p.lstat().st_size) for p in tmp_path.rglob("*"))
    assert after == before, "detect must not create, touch or resize any file"
    assert list(home.iterdir()) == [], "detect must not write into HOME"


def test_detect_this_repository_finds_python_uv_ci_commands() -> None:
    repo_root = Path(__file__).resolve().parents[3]

    result = detect(repo_root)

    app = result.root_apps[0]
    assert app.path == "."
    assert app.languages == ("python",)
    assert app.package_manager == "uv"
    assert ci_check_cmd(app) == (
        "uv run ruff check . && uv run ruff format --check . && uv run pyright && uv run pytest"
    )
    assert "CLAUDE.md" in result.existing_harness
