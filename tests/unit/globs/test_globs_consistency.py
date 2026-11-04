import json
import subprocess
from pathlib import Path

from seh.evals.checker import run_checks
from seh.evals.fixtures import load_case, materialize
from seh.policy import ALLOW_ALL, Policy
from seh.runtime.worktree import WorktreeManager
from seh.tools.registry import ToolContext, default_registry


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.com", *args],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def test_worktree_scope_violations_rejects_nested_path_for_single_star(tmp_path: Path):
    manager = WorktreeManager(tmp_path, run_id="r1")

    violations = manager.scope_violations(["src/a.py", "src/x/a.py"], ["src/*.py"])

    assert violations == ("src/x/a.py",)


async def test_git_scope_check_rejects_nested_path_for_single_star(tmp_path: Path):
    _git(tmp_path, "init", "-q")
    (tmp_path / "README").write_text("r\n")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-q", "-m", "init")
    base = _git(tmp_path, "rev-parse", "HEAD")
    (tmp_path / "src" / "x").mkdir(parents=True)
    (tmp_path / "src" / "a.py").write_text("a\n")
    (tmp_path / "src" / "x" / "a.py").write_text("a\n")
    ctx = ToolContext(
        root=tmp_path,
        policy=Policy(tool_allowlist=ALLOW_ALL),
        granted_permissions=frozenset({"read:repository"}),
    )

    result = await default_registry().execute(
        "git.scope_check", {"base": base, "allowlist": ["src/*.py"]}, ctx
    )

    assert result == {"ok": False, "outside": ["src/x/a.py"]}


async def test_checker_diff_scope_rejects_nested_path_for_single_star(tmp_path: Path):
    case_dir = tmp_path / "E42"
    (case_dir / "repo").mkdir(parents=True)
    (case_dir / "repo" / "a.txt").write_text("a\n")
    (case_dir / "case.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "id": "E42",
                "title": "t",
                "split": "training",
                "kind": "bugfix",
                "task": {"goal": "g", "acceptance": []},
                "repo": "repo/",
                "checks": [{"id": "scope", "type": "diff_scope", "allow": ["src/*.py"]}],
                "write_allowlist": ["src/*.py"],
                "expected_verdict_for_noop": "FAIL",
            }
        )
    )
    case = load_case(case_dir)
    work = materialize(case, tmp_path / "work")
    (work / "src" / "x").mkdir(parents=True)
    (work / "src" / "a.py").write_text("a\n")
    (work / "src" / "x" / "a.py").write_text("a\n")

    _, results = await run_checks(case, work)

    scope = next(r for r in results if r.check_id == "scope")
    assert (scope.passed, scope.detail) == (False, "outside allowlist: src/x/a.py")
