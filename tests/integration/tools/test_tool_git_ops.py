import subprocess
from pathlib import Path

from seh.policy import ALLOW_ALL, Policy
from seh.tools.registry import ToolContext, default_registry


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.com", *args],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _repo(root: Path) -> str:
    _git(root, "init", "-q")
    (root / "a.py").write_text("a = 1\n")
    (root / "docs").mkdir()
    (root / "docs" / "r.md").write_text("r\n")
    _git(root, "add", ".")
    _git(root, "commit", "-q", "-m", "init")
    base = _git(root, "rev-parse", "HEAD")
    (root / "a.py").write_text("a = 2\n")
    (root / "docs" / "r.md").write_text("r2\n")
    (root / "new.txt").write_text("n\n")
    return base


def _ctx(root: Path) -> ToolContext:
    return ToolContext(
        root=root,
        policy=Policy(tool_allowlist=ALLOW_ALL),
        granted_permissions=frozenset({"read:repository"}),
    )


async def test_diff_names_lists_changed_and_untracked(tmp_path: Path):
    base = _repo(tmp_path)

    result = await default_registry().execute("git.diff_names", {"base": base}, _ctx(tmp_path))

    assert result == {"changed": ["a.py", "docs/r.md"], "untracked": ["new.txt"]}


async def test_scope_check_reports_files_outside_allowlist(tmp_path: Path):
    base = _repo(tmp_path)

    result = await default_registry().execute(
        "git.scope_check", {"base": base, "allowlist": ["a.py", "docs/**"]}, _ctx(tmp_path)
    )

    assert result == {"ok": False, "outside": ["new.txt"]}


async def test_scope_check_ok_when_all_inside_allowlist(tmp_path: Path):
    base = _repo(tmp_path)

    result = await default_registry().execute(
        "git.scope_check", {"base": base, "allowlist": ["*.py", "*.txt", "docs/*"]}, _ctx(tmp_path)
    )

    assert result == {"ok": True, "outside": []}


async def test_diff_names_rejects_option_like_base(tmp_path: Path):
    _repo(tmp_path)

    try:
        await default_registry().execute(
            "git.diff_names", {"base": "--output=evil"}, _ctx(tmp_path)
        )
    except Exception as exc:
        assert getattr(exc, "code", None) == "INVALID_INPUT"
    else:
        raise AssertionError("expected ToolError")
