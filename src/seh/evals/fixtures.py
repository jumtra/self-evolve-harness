"""docs/evals.md の eval case を読み、評価用の作業 repo を作る。"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from seh.contracts import VerdictStatus

BASELINE_TAG = "seh-baseline"
FIXTURE_SUFFIX = ".fixture"
DEFAULT_SUITE_ROOT = Path("tests/fixtures/eval")

_ID = re.compile(r"E\d\d")
_SPLITS = frozenset({"training", "regression", "holdout"})
_KINDS = frozenset(
    {
        "bugfix",
        "feature",
        "calc",
        "refactor",
        "parallel",
        "provider",
        "security",
        "self_eval",
        "budget",
        "migration",
    }
)
# 作業 repo に残る実行副産物を untracked 扱いにしない
_EXCLUDES = ("__pycache__/", "*.pyc", ".pytest_cache/")
_GIT_ENV = {
    "GIT_AUTHOR_NAME": "seh-eval",
    "GIT_AUTHOR_EMAIL": "seh-eval@example.invalid",
    "GIT_COMMITTER_NAME": "seh-eval",
    "GIT_COMMITTER_EMAIL": "seh-eval@example.invalid",
    "GIT_AUTHOR_DATE": "2000-01-01T00:00:00+00:00",
    "GIT_COMMITTER_DATE": "2000-01-01T00:00:00+00:00",
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
}


class FixtureError(ValueError):
    pass


@dataclass(frozen=True)
class TaskSpec:
    goal: str
    acceptance: tuple[str, ...]


@dataclass(frozen=True)
class CheckSpec:
    id: str
    type: str
    params: Mapping[str, Any]


@dataclass(frozen=True)
class EvalCase:
    schema_version: int
    id: str
    title: str
    split: str
    kind: str
    task: TaskSpec
    repo_dir: Path
    expand_suffix: bool
    checks: tuple[CheckSpec, ...]
    write_allowlist: tuple[str, ...]
    expected_verdict_for_noop: VerdictStatus
    # NAME -> secret_template 指示。生成値は materialize 時にだけ作る
    secrets: Mapping[str, Mapping[str, Any]]


def generate_secret(template: Mapping[str, Any]) -> str:
    inner = template.get("secret_template")
    if not isinstance(inner, dict):
        raise FixtureError("secret_template object required")
    parts = inner.get("parts")
    if parts is not None:
        if not isinstance(parts, list) or not all(isinstance(p, str) for p in parts):
            raise FixtureError("secret_template.parts must be a list of str")
        return "".join(parts)
    prefix, fill, suffix = inner.get("prefix", ""), inner.get("fill", ""), inner.get("suffix", "")
    length = inner.get("length", 0)
    if not (isinstance(prefix, str) and isinstance(fill, str) and isinstance(suffix, str)):
        raise FixtureError("secret_template prefix/fill/suffix must be str")
    if not isinstance(length, int) or isinstance(length, bool) or length < 0:
        raise FixtureError("secret_template.length must be a non-negative int")
    return prefix + fill * length + suffix


def _require(data: Mapping[str, Any], key: str, typ: type | tuple[type, ...]) -> Any:
    value = data.get(key)
    if not isinstance(value, typ) or (typ is int and isinstance(value, bool)):
        raise FixtureError(f"field {key!r} missing or has wrong type")
    return value


def _str_tuple(value: Any, label: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise FixtureError(f"{label} must be a list of str")
    return tuple(value)


def load_case(path: Path) -> EvalCase:
    case_json = path / "case.json" if path.is_dir() else path
    try:
        data = json.loads(case_json.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise FixtureError(f"cannot read {case_json}: {e}") from e
    if not isinstance(data, dict):
        raise FixtureError("case.json must be an object")

    if data.get("schema_version") != 1:
        raise FixtureError("schema_version must be 1")
    case_id = _require(data, "id", str)
    if not _ID.fullmatch(case_id) or case_id != case_json.parent.name:
        raise FixtureError(f"id {case_id!r} must match E\\d\\d and the directory name")
    split = _require(data, "split", str)
    kind = _require(data, "kind", str)
    if split not in _SPLITS:
        raise FixtureError(f"unknown split {split!r}")
    if kind not in _KINDS:
        raise FixtureError(f"unknown kind {kind!r}")
    task = _require(data, "task", dict)
    expected = _require(data, "expected_verdict_for_noop", str)
    try:
        expected_status = VerdictStatus(expected)
    except ValueError as e:
        raise FixtureError(f"unknown expected_verdict_for_noop {expected!r}") from e

    raw_checks = _require(data, "checks", list)
    if not raw_checks:
        raise FixtureError("checks must have at least one entry")
    checks: list[CheckSpec] = []
    for raw in raw_checks:
        if not isinstance(raw, dict):
            raise FixtureError("each check must be an object")
        check_id = _require(raw, "id", str)
        check_type = _require(raw, "type", str)
        if any(c.id == check_id for c in checks):
            raise FixtureError(f"duplicate check id {check_id!r}")
        params = {k: v for k, v in raw.items() if k not in ("id", "type")}
        checks.append(CheckSpec(id=check_id, type=check_type, params=params))

    secrets = data.get("secrets", {})
    if not isinstance(secrets, dict):
        raise FixtureError("secrets must be an object")
    for template in secrets.values():
        generate_secret(template)  # 不正な指示はロード時に検出する

    expand = data.get("expand_suffix", False)
    if not isinstance(expand, bool):
        raise FixtureError("expand_suffix must be bool")

    return EvalCase(
        schema_version=1,
        id=case_id,
        title=_require(data, "title", str),
        split=split,
        kind=kind,
        task=TaskSpec(
            goal=_require(task, "goal", str),
            acceptance=_str_tuple(task.get("acceptance", []), "task.acceptance"),
        ),
        repo_dir=case_json.parent / _require(data, "repo", str),
        expand_suffix=expand,
        checks=tuple(checks),
        write_allowlist=_str_tuple(data.get("write_allowlist"), "write_allowlist"),
        expected_verdict_for_noop=expected_status,
        secrets=secrets,
    )


def load_suite(root: Path = DEFAULT_SUITE_ROOT) -> list[EvalCase]:
    return [load_case(p) for p in sorted(root.glob("E[0-9][0-9]/case.json"))]


def git_env() -> dict[str, str]:
    env = {k: os.environ[k] for k in ("PATH", "HOME", "TMPDIR") if k in os.environ}
    env.update(_GIT_ENV)
    return env


def _git(args: list[str], cwd: Path) -> None:
    result = subprocess.run(
        ["git", *args], cwd=cwd, env=git_env(), capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        raise FixtureError(f"git {args[0]} failed: {result.stderr.strip()}")


def _rewrite_files(work: Path, case: EvalCase) -> None:
    secrets = {name: generate_secret(t) for name, t in case.secrets.items()}
    for path in sorted(work.rglob("*")):
        if path.is_symlink() or not path.is_file() or ".git" in path.relative_to(work).parts:
            continue
        if secrets:
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                text = None
            if text is not None:
                replaced = text
                for name, value in secrets.items():
                    replaced = replaced.replace("{" + name + "}", value)
                if replaced != text:
                    path.write_text(replaced, encoding="utf-8")
        if case.expand_suffix and path.name.endswith(FIXTURE_SUFFIX):
            path.rename(path.with_name(path.name.removesuffix(FIXTURE_SUFFIX)))


def materialize(case: EvalCase, dest: Path) -> Path:
    if not case.repo_dir.is_dir():
        raise FixtureError(f"repo dir not found: {case.repo_dir}")
    if dest.exists() and (not dest.is_dir() or any(dest.iterdir())):
        raise FixtureError(f"destination must be empty: {dest}")
    shutil.copytree(case.repo_dir, dest, symlinks=True, dirs_exist_ok=True)
    _rewrite_files(dest, case)
    _git(["init", "-q"], dest)
    with (dest / ".git" / "info" / "exclude").open("a", encoding="utf-8") as f:
        f.write("\n".join(_EXCLUDES) + "\n")
    _git(["add", "-A"], dest)
    _git(["commit", "-q", "--allow-empty", "-m", "baseline"], dest)
    _git(["tag", BASELINE_TAG], dest)
    return dest
