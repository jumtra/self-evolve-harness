"""操作のリスク分類と無人実行可否の判定。

承認を与える経路（assume_yes 等）は意図的に存在させない。承認は人間発行の
ApprovalToken のみ。EvolutionEngine から改変されないよう PROTECTED_PATH_GLOBS に自身を含む。
"""

from __future__ import annotations

import posixpath
import re
import shlex
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Literal

from seh.contracts import ApprovalToken, RiskRank

PROTECTED_PATH_GLOBS: tuple[str, ...] = (
    ".harness/config.toml",
    ".harness/policy/**",
    "src/seh/policy.py",
    ".claude/settings.json",
    ".agents/hooks.json",
    ".codex/hooks.json",
    ".codex/rules/**",
    ".opencode/plugins/**",
    ".github/workflows/**",
)

_SHARED_CONFIG_NAMES = frozenset({"pyproject.toml", "package.json", "CLAUDE.md", "AGENTS.md"})
_BULK_CHANGE_THRESHOLD = 10
_RANK_ORDER = {RiskRank.R0: 0, RiskRank.R1: 1, RiskRank.R2: 2}
_WRAPPERS = frozenset({"sudo", "env", "nohup", "time", "command", "exec"})
_SHELLS = frozenset({"sh", "bash", "zsh", "dash"})
_FETCHERS = frozenset({"curl", "wget"})
_PUBLISH_COMMANDS = frozenset({"npm", "yarn", "pnpm", "uv"})
_SQL_DESTRUCTIVE = re.compile(r"\b(drop\s+(table|database|schema)|truncate)\b", re.IGNORECASE)
_SQL_DELETE_FROM = re.compile(r"\bdelete\s+from\b[^;]*", re.IGNORECASE)
_SEPARATORS = frozenset({";", "&", "&&", "|", "||", "|&", "(", ")", "<", "<<", "<<<", "<&"})
_REDIRECTS = frozenset({">", ">>", ">|", ">&"})
_ENV_ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")

ActionKind = Literal["command", "write", "delete", "external", "tool"]
Actor = Literal["agent", "evolver", "human"]


@dataclass(frozen=True)
class Action:
    kind: ActionKind
    target: str
    argv: tuple[str, ...] = ()


@dataclass(frozen=True)
class Decision:
    allowed: bool
    risk: RiskRank
    reason_code: str
    requires_approval: bool
    message: str


@dataclass(frozen=True)
class _Assessment:
    risk: RiskRank
    external: bool = False


def _max(a: _Assessment, b: _Assessment) -> _Assessment:
    risk = a.risk if _RANK_ORDER[a.risk] >= _RANK_ORDER[b.risk] else b.risk
    return _Assessment(risk, a.external or b.external)


_R0 = _Assessment(RiskRank.R0)
_R1 = _Assessment(RiskRank.R1)
_R2 = _Assessment(RiskRank.R2)
_EXTERNAL = _Assessment(RiskRank.R1, external=True)


def is_protected_path(path: str) -> bool:
    candidate = Path(path)
    if candidate.is_absolute():
        # リポジトリ外を指す絶対パスは保護扱い。cwd をリポジトリ根とみなす。
        try:
            candidate = candidate.relative_to(Path.cwd())
        except ValueError:
            return True
    normalized = posixpath.normpath(candidate.as_posix())
    if normalized == ".." or normalized.startswith("../"):
        return True
    # macOS 等の大文字小文字非区別 FS で迂回されないよう小文字化して比較する
    lowered = normalized.lower()
    return any(fnmatchcase(lowered, glob.lower()) for glob in PROTECTED_PATH_GLOBS)


def _assess_path(path: str) -> _Assessment:
    if is_protected_path(path):
        return _R2
    if posixpath.basename(path) in _SHARED_CONFIG_NAMES:
        return _R1
    return _R0


def classify_paths(paths: Sequence[str]) -> RiskRank:
    assessment = _R1 if len(paths) > _BULK_CHANGE_THRESHOLD else _R0
    for path in paths:
        assessment = _max(assessment, _assess_path(path))
    return assessment.risk


def classify(action: Action) -> RiskRank:
    return _assess(action).risk


def _assess(action: Action) -> _Assessment:
    match action.kind:
        case "command":
            return _assess_command_line(action.target)
        case "write" | "delete":
            return _assess_path(action.target)
        case "external":
            return _EXTERNAL
        case "tool":
            return _R0


def _split_command_line(command: str) -> tuple[list[list[str]], list[str], list[str]] | None:
    """(セグメント列, 各セグメント直前の区切り, リダイレクト先) を返す。解析不能は None。"""
    lexer = shlex.shlex(command.replace("\n", ";"), posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    segments: list[list[str]] = [[]]
    separators: list[str] = [""]
    redirects: list[str] = []
    expect_redirect = False
    try:
        tokens = list(lexer)
    except ValueError:
        return None
    for token in tokens:
        if expect_redirect:
            redirects.append(token)
            expect_redirect = False
        elif token in _REDIRECTS:
            expect_redirect = True
        elif token in _SEPARATORS:
            if segments[-1]:
                segments.append([])
                separators.append(token)
        else:
            segments[-1].append(token)
    return [s for s in segments if s], separators, redirects


def _assess_command_line(command: str) -> _Assessment:
    parsed = _split_command_line(command)
    if parsed is None:
        return _R2
    segments, _, redirects = parsed
    assessment = _R0
    if _SQL_DESTRUCTIVE.search(command):
        assessment = _R2
    for match in _SQL_DELETE_FROM.finditer(command):
        if "where" not in match.group(0).lower():
            assessment = _R2
    for target in redirects:
        assessment = _max(assessment, _assess_path(target))
    for index, argv in enumerate(segments):
        assessment = _max(assessment, _assess_argv(_strip_wrappers(argv)))
        if index > 0 and _is_fetch_pipe_to_shell(segments[index - 1], argv, command):
            assessment = _R2
    return assessment


def _is_fetch_pipe_to_shell(previous: list[str], current: list[str], command: str) -> bool:
    previous_cmd = _command_name(_strip_wrappers(previous))
    current_cmd = _command_name(_strip_wrappers(current))
    return previous_cmd in _FETCHERS and current_cmd in _SHELLS and "|" in command


def _strip_wrappers(argv: list[str]) -> list[str]:
    rest = list(argv)
    while rest and (rest[0] in _WRAPPERS or _ENV_ASSIGNMENT.match(rest[0])):
        rest = rest[1:]
    return rest


def _command_name(argv: list[str]) -> str:
    return posixpath.basename(argv[0]) if argv else ""


def _short_flags(args: Sequence[str]) -> str:
    return "".join(a[1:] for a in args if a.startswith("-") and not a.startswith("--"))


def _assess_argv(argv: list[str]) -> _Assessment:
    name = _command_name(argv)
    args = argv[1:]
    sub = next((a for a in args if not a.startswith("-")), "")
    handlers = {
        "rm": _assess_rm,
        "find": _assess_find,
        "git": _assess_git,
        "chmod": _assess_chmod,
        "chown": _assess_chown,
        "gh": _assess_gh,
        "twine": lambda a: _R2 if "upload" in a else _R0,
        "pip": lambda a: _R2 if "upload" in a else _R0,
        "aws": lambda a: _R2 if sub == "iam" else _R0,
        "gcloud": lambda a: _R2 if any("iam" in x for x in a) else _R0,
        "helm": lambda a: _R2 if sub in {"upgrade", "install"} else _R0,
        "kubectl": _assess_kubectl,
        "terraform": lambda a: _R2 if sub in {"apply", "destroy"} else _R0,
        "tofu": lambda a: _R2 if sub in {"apply", "destroy"} else _R0,
    }
    if name in _PUBLISH_COMMANDS:
        return _R2 if sub == "publish" else _R0
    handler = handlers.get(name)
    return handler(args) if handler else _R0


def _assess_rm(args: list[str]) -> _Assessment:
    flags = _short_flags(args)
    recursive = "r" in flags or "R" in flags or "--recursive" in args
    return _R2 if recursive else _R0


def _assess_find(args: list[str]) -> _Assessment:
    if "-delete" in args or ("-exec" in args and "rm" in args):
        return _R2
    return _R0


def _assess_chmod(args: list[str]) -> _Assessment:
    recursive = "R" in _short_flags(args) or "--recursive" in args
    return _R2 if recursive and any(a in {"777", "a+rwx", "o+w"} for a in args) else _R0


def _assess_chown(args: list[str]) -> _Assessment:
    return _R2 if "R" in _short_flags(args) or "--recursive" in args else _R0


def _assess_kubectl(args: list[str]) -> _Assessment:
    sub = next((a for a in args if not a.startswith("-")), "")
    if sub not in {"apply", "delete"}:
        return _R0
    return _R2 if any("prod" in a.lower() for a in args) else _R1


def _assess_gh(args: list[str]) -> _Assessment:
    positional = [a for a in args if not a.startswith("-")][:2]
    if positional == ["release", "create"]:
        return _R2
    if positional in (["pr", "create"], ["pr", "merge"]):
        return _EXTERNAL
    return _R0


def _assess_git(args: list[str]) -> _Assessment:
    rest = list(args)
    # `git -C dir` / `git -c k=v` のグローバルオプションを飛ばして副コマンドに到達する
    while rest and rest[0].startswith("-"):
        rest = rest[2:] if rest[0] in {"-C", "-c"} else rest[1:]
    if not rest:
        return _R0
    sub, sub_args = rest[0], rest[1:]
    flags = _short_flags(sub_args)
    if sub == "push":
        forced = (
            "f" in flags
            or any(a.startswith(("--force", "--mirror", "--delete")) for a in sub_args)
            or any(a.startswith("+") for a in sub_args)
        )
        return _R2 if forced else _EXTERNAL
    if sub == "reset" and "--hard" in sub_args:
        return _R1
    if sub == "clean":
        return _R2 if "d" in flags or "x" in flags or "X" in flags else _R1
    return _R0


class Policy:
    def __init__(
        self,
        *,
        tool_allowlist: frozenset[str] = frozenset(),
        command_allowlist: frozenset[str] = frozenset(),
    ) -> None:
        self._tool_allowlist = tool_allowlist
        self._command_allowlist = command_allowlist

    def authorize(
        self,
        action: Action,
        *,
        unattended: bool,
        token: ApprovalToken | None = None,
        token_scope: str | None = None,
        target_digest: str | None = None,
        now: datetime,
    ) -> Decision:
        assessment = _assess(action)
        if assessment.risk == RiskRank.R2:
            code = "R2_REQUIRES_APPROVAL"
        elif assessment.external:
            code = "EXTERNAL_EFFECT_REQUIRES_APPROVAL"
        else:
            return Decision(True, assessment.risk, "ALLOWED", False, "approval not required")
        if unattended and _token_approves(token, token_scope, target_digest, now):
            return Decision(True, assessment.risk, "APPROVED_BY_TOKEN", False, "approved by token")
        message = "approval token required" if unattended else "human confirmation required"
        return Decision(False, assessment.risk, code, True, message)

    def authorize_tool(self, name: str) -> Decision:
        if self._tool_allowlist and name not in self._tool_allowlist:
            return Decision(
                False, RiskRank.R0, "TOOL_NOT_ALLOWED", False, f"tool not allowed: {name}"
            )
        return Decision(True, RiskRank.R0, "ALLOWED", False, "tool allowed")

    def authorize_command(self, argv: Sequence[str]) -> Decision:
        name = posixpath.basename(argv[0]) if argv else ""
        if name not in self._command_allowlist:
            return Decision(
                False, RiskRank.R0, "COMMAND_NOT_ALLOWED", False, f"command not allowed: {name}"
            )
        return Decision(True, RiskRank.R0, "ALLOWED", False, "command allowed")

    def authorize_write(self, path: str, *, actor: Actor) -> Decision:
        risk = _assess_path(path).risk
        if not is_protected_path(path) or actor == "human":
            return Decision(True, risk, "ALLOWED", False, "write allowed")
        if actor == "evolver":
            return Decision(False, risk, "PROTECTED_PATH", False, f"protected path: {path}")
        return Decision(
            False, risk, "PROTECTED_PATH_REQUIRES_APPROVAL", True, f"protected path: {path}"
        )


def _token_approves(
    token: ApprovalToken | None,
    token_scope: str | None,
    target_digest: str | None,
    now: datetime,
) -> bool:
    if token is None or token_scope is None or target_digest is None:
        return False
    # AI 自己発行のトークンで承認をバイパスさせない
    if token.issued_by != "human":
        return False
    return token.is_valid_for(token_scope, target_digest, now)
