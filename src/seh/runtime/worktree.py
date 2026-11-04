"""ワークユニット単位の git worktree 隔離・書込範囲検査・統合。"""

from __future__ import annotations

import asyncio
import os
import re
import shutil
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from seh.globs import outside_allowlist
from seh.redaction import mask_text
from seh.runtime.process import DEFAULT_ENV_ALLOWLIST, build_env, run_process

_SAFE_ID = re.compile(r"[A-Za-z0-9._-]+")
_GIT_TIMEOUT_SECONDS = 60
_IDENTITY = {
    "GIT_AUTHOR_NAME": "seh",
    "GIT_AUTHOR_EMAIL": "seh@localhost",
    "GIT_COMMITTER_NAME": "seh",
    "GIT_COMMITTER_EMAIL": "seh@localhost",
}
_INTEGRATION_DIR = "_integration"


class WorktreeError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code


@dataclass(frozen=True)
class UnitWorkspace:
    node_id: str
    path: Path
    branch: str
    base_commit: str


@dataclass(frozen=True)
class IntegrationResult:
    merged: tuple[str, ...]
    conflicts: tuple[tuple[str, tuple[str, ...]], ...]
    head: str


def _check_id(value: str, label: str) -> str:
    # パス・ブランチ名へ埋め込むため、トラバーサルやオプション注入を入口で断つ
    if not _SAFE_ID.fullmatch(value) or value.startswith(("-", ".")):
        raise ValueError(f"unsafe {label}: {value!r}")
    return value


class WorktreeManager:
    def __init__(self, repo: Path, *, run_id: str, root: Path | None = None) -> None:
        self._repo = repo
        self._run_id = _check_id(run_id, "run_id")
        self._root = root or repo / ".harness" / "state" / "worktrees" / run_id
        self._units: list[UnitWorkspace] = []
        self._integration: Path | None = None
        # 同一 repo への worktree add は .git 配下のロックを取り合うため直列化する
        self._create_lock = asyncio.Lock()

    async def _git(self, args: Sequence[str], cwd: Path, *, check: bool = True) -> str:
        env = build_env(DEFAULT_ENV_ALLOWLIST, os.environ, _IDENTITY)
        result = await run_process(
            ["git", "-c", "commit.gpgsign=false", *args],
            cwd=cwd,
            env=env,
            timeout_seconds=_GIT_TIMEOUT_SECONDS,
        )
        if check and (result.timed_out or result.exit_code != 0):
            stderr = mask_text(result.stderr.decode(errors="replace")[-500:])
            raise WorktreeError("GIT_FAILED", f"git {args[0]} failed: {stderr}")
        return result.stdout.decode(errors="replace")

    async def base_commit(self) -> str:
        probe = await run_process(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=self._repo,
            env=build_env(DEFAULT_ENV_ALLOWLIST, os.environ),
            timeout_seconds=_GIT_TIMEOUT_SECONDS,
        )
        if probe.exit_code != 0:
            raise WorktreeError("NOT_A_GIT_REPO", str(self._repo))
        status = await self._git(
            [
                "status",
                "--porcelain",
                "--untracked-files=all",
                "--",
                ".",
                ":(exclude).harness/state",
            ],
            self._repo,
        )
        if status.strip():
            raise WorktreeError("DIRTY_BASE", "working tree has uncommitted changes")
        return (await self._git(["rev-parse", "HEAD"], self._repo)).strip()

    async def create(self, node_id: str, *, base: str) -> UnitWorkspace:
        _check_id(node_id, "node_id")
        branch = f"seh/{self._run_id}/{node_id}"
        path = self._root / node_id
        async with self._create_lock:
            existing = await self._git(["branch", "--list", branch], self._repo)
            if path.exists() or existing.strip():
                raise WorktreeError("WORKTREE_EXISTS", f"{node_id}")
            self._root.mkdir(parents=True, exist_ok=True)
            await self._git(["worktree", "add", "-b", branch, str(path), base], self._repo)
            commit = (await self._git(["rev-parse", "HEAD"], path)).strip()
        ws = UnitWorkspace(node_id=node_id, path=path, branch=branch, base_commit=commit)
        self._units.append(ws)
        return ws

    async def changed_paths(self, ws: UnitWorkspace) -> tuple[str, ...]:
        # rename は旧パス・新パスの双方を書込対象として扱うため検出を無効化する
        tracked = await self._git(
            ["diff", "--name-only", "--no-renames", "-z", ws.base_commit], ws.path
        )
        untracked = await self._git(["ls-files", "--others", "--exclude-standard", "-z"], ws.path)
        names = {n for n in (tracked + untracked).split("\0") if n}
        return tuple(sorted(names))

    def scope_violations(self, changed: Sequence[str], allowlist: Sequence[str]) -> tuple[str, ...]:
        return outside_allowlist(changed, allowlist)

    async def commit_unit(self, ws: UnitWorkspace, message: str) -> str:
        await self._git(["add", "-A"], ws.path)
        staged = await self._git(["diff", "--cached", "--name-only"], ws.path)
        if staged.strip():
            await self._git(["commit", "-m", message], ws.path)
        return (await self._git(["rev-parse", "HEAD"], ws.path)).strip()

    async def integrate(
        self, units: Sequence[UnitWorkspace], *, target_branch: str
    ) -> IntegrationResult:
        if not units:
            raise ValueError("units must not be empty")
        path = self._root / _INTEGRATION_DIR
        if path.exists():
            await self._git(["worktree", "remove", "--force", str(path)], self._repo, check=False)
            shutil.rmtree(path, ignore_errors=True)
        exists = (await self._git(["branch", "--list", target_branch], self._repo)).strip()
        self._root.mkdir(parents=True, exist_ok=True)
        if exists:
            await self._git(["worktree", "add", str(path), target_branch], self._repo)
        else:
            await self._git(
                ["worktree", "add", "-b", target_branch, str(path), units[0].base_commit],
                self._repo,
            )
        self._integration = path

        merged: list[str] = []
        conflicts: list[tuple[str, tuple[str, ...]]] = []
        for unit in units:
            merge = await run_process(
                ["git", "-c", "commit.gpgsign=false", "merge", "--no-ff", "--no-edit", unit.branch],
                cwd=path,
                env=build_env(DEFAULT_ENV_ALLOWLIST, os.environ, _IDENTITY),
                timeout_seconds=_GIT_TIMEOUT_SECONDS,
            )
            if merge.exit_code == 0:
                merged.append(unit.node_id)
                continue
            unmerged = await self._git(["diff", "--name-only", "--diff-filter=U"], path)
            await self._git(["merge", "--abort"], path, check=False)
            paths = tuple(sorted(p for p in unmerged.splitlines() if p))
            if not paths:
                stderr = mask_text(merge.stderr.decode(errors="replace")[-500:])
                raise WorktreeError("GIT_FAILED", f"git merge failed: {stderr}")
            conflicts.append((unit.node_id, paths))
        head = (await self._git(["rev-parse", "HEAD"], path)).strip()
        return IntegrationResult(merged=tuple(merged), conflicts=tuple(conflicts), head=head)

    async def cleanup(self, *, keep_branches: bool = False) -> None:
        paths = [u.path for u in self._units]
        if self._integration is not None:
            paths.append(self._integration)
        for path in paths:
            await self._git(["worktree", "remove", "--force", str(path)], self._repo, check=False)
            shutil.rmtree(path, ignore_errors=True)
        await self._git(["worktree", "prune"], self._repo)
        if not keep_branches:
            for unit in self._units:
                await self._git(["branch", "-D", unit.branch], self._repo, check=False)
