"""操作のリスク分類と無人実行可否の判定。

承認を与える経路（assume_yes 等）は意図的に存在させない。承認は人間発行の
ApprovalToken のみ。EvolutionEngine から改変されないよう PROTECTED_PATH_GLOBS に自身を含む。

コマンド解析（split_segments / strip_wrappers）と機密・設定ファイル述語はここを唯一の実装とし、
events / detect はこれを import する。
"""

from __future__ import annotations

import hashlib
import posixpath
import re
import shlex
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Literal

from seh.contracts import ApprovalToken, RiskRank

PROTECTED_PATH_GLOBS: tuple[str, ...] = (
    ".harness/config.toml",
    ".harness/policy/**",
    ".harness/backups/**",
    ".harness/ownership.json",
    ".harness/generated.lock.json",
    "src/seh/policy.py",
    ".claude/settings.json",
    "**/.claude/settings.json",
    ".agents/hooks.json",
    "**/.agents/hooks.json",
    ".codex/hooks.json",
    "**/.codex/hooks.json",
    ".codex/rules/**",
    "**/.codex/rules/**",
    ".opencode/plugins/**",
    "**/.opencode/plugins/**",
    ".github/workflows/**",
)

SENSITIVE_NAME_GLOBS: tuple[str, ...] = (
    ".env",
    ".env.*",
    "*.pem",
    "*.key",
    "*credential*",
    "*secret*",
)
_SENSITIVE_EXEMPT_NAMES = frozenset({".env.example", ".env.sample", ".env.template"})

TOOL_CONFIG_GLOBS: tuple[str, ...] = (
    ".eslintrc*",
    "eslint.config.*",
    ".prettierrc*",
    "prettier.config.*",
    "biome.json",
    "biome.jsonc",
    ".stylelintrc*",
    "stylelint.config.*",
    "ruff.toml",
    ".ruff.toml",
    "pyrightconfig.json",
    "mypy.ini",
    ".mypy.ini",
    ".flake8",
    "tsconfig*.json",
    ".golangci.*",
    "rustfmt.toml",
    ".rustfmt.toml",
    "clippy.toml",
    ".clippy.toml",
    ".editorconfig",
    "Directory.Build.props",
    ".clang-format",
    ".clang-tidy",
    ".tflint.hcl",
)

ALLOW_ALL: frozenset[str] = frozenset({"*"})

_SHARED_CONFIG_NAMES = frozenset({"pyproject.toml", "package.json", "CLAUDE.md", "AGENTS.md"})
_BULK_CHANGE_THRESHOLD = 10
_RANK_ORDER = {RiskRank.R0: 0, RiskRank.R1: 1, RiskRank.R2: 2}
_PUBLISH_COMMANDS = frozenset({"npm", "yarn", "pnpm", "uv"})
_SQL_DESTRUCTIVE = re.compile(r"\b(drop\s+(table|database|schema)|truncate)\b", re.IGNORECASE)
_SQL_DELETE_FROM = re.compile(r"\bdelete\s+from\b[^;]*", re.IGNORECASE)
_SUBSTITUTION = re.compile(r"`|\$\(|<\(|>\(")
_OPERATOR_CHARS = frozenset("();<>|&")
_ENV_ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
# 区切りとして捨てるシェル予約語。コマンド位置（セグメント先頭）にある時だけ予約語として扱う
_RESERVED_WORDS = frozenset(
    {
        "then",
        "do",
        "else",
        "elif",
        "fi",
        "done",
        "{",
        "}",
        "!",
        "if",
        "while",
        "until",
        "for",
        "case",
        "esac",
        "select",
    }
)
_ALWAYS_UNANALYZABLE = frozenset({"eval", "source", ".", "xargs"})
_FIND_UNANALYZABLE = frozenset({"-exec", "-execdir", "-ok", "-okdir", "-delete"})
_POWERSHELLS = frozenset({"pwsh", "powershell"})
_POWERSHELL_INLINE = frozenset({"-c", "-command", "-e", "-ec", "-enc", "-encodedcommand"})
_PATH_WRITERS = frozenset(
    {"tee", "cp", "mv", "install", "ln", "rsync", "truncate", "chmod", "chown", "touch", "rm"}
)

ActionKind = Literal["command", "write", "delete", "external", "tool"]
Actor = Literal["agent", "evolver", "human"]


class UnparseableCommand(ValueError):
    pass


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


def action_digest(action: Action) -> str:
    payload = "\0".join((action.kind, action.target, *action.argv))
    return hashlib.sha256(payload.encode()).hexdigest()


# --- パス述語 -----------------------------------------------------------------


def is_protected_path(path: str, *, root: Path | None = None) -> bool:
    candidate = Path(path)
    if candidate.is_absolute():
        # リポジトリ外を指す絶対パスは保護扱い。root 未指定時のみ cwd をリポジトリ根とみなす。
        try:
            candidate = candidate.relative_to(root if root is not None else Path.cwd())
        except ValueError:
            return True
    normalized = posixpath.normpath(candidate.as_posix())
    if normalized == ".." or normalized.startswith("../"):
        return True
    # macOS 等の大文字小文字非区別 FS で迂回されないよう小文字化して比較する
    lowered = normalized.lower()
    return any(_matches_protected(lowered, glob.lower()) for glob in PROTECTED_PATH_GLOBS)


def _matches_protected(lowered: str, glob: str) -> bool:
    if fnmatchcase(lowered, glob):
        return True
    # `dir/**` はディレクトリ自体にも一致させる（`.harness/policy` を丸ごと差し替えられないように）
    return glob.endswith("/**") and lowered == glob.removesuffix("/**")


def _matches_name(path: str, globs: Sequence[str]) -> bool:
    name = posixpath.basename(path).lower()
    return any(fnmatchcase(name, glob.lower()) for glob in globs)


def is_sensitive_path(path: str) -> bool:
    if posixpath.basename(path).lower() in _SENSITIVE_EXEMPT_NAMES:
        return False
    return _matches_name(path, SENSITIVE_NAME_GLOBS)


def is_tool_config_path(path: str) -> bool:
    return _matches_name(path, TOOL_CONFIG_GLOBS)


def _assess_path(path: str) -> _Assessment:
    if path == "/dev/null":
        return _R0
    if is_protected_path(path) or is_sensitive_path(path):
        return _R2
    if is_tool_config_path(path) or posixpath.basename(path) in _SHARED_CONFIG_NAMES:
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


# --- トークナイザ -------------------------------------------------------------


@dataclass(frozen=True)
class _Segment:
    argv: tuple[str, ...]
    redirects: tuple[str, ...]
    heredoc: bool
    piped: bool


def _is_operator(token: str) -> bool:
    return all(ch in _OPERATOR_CHARS for ch in token)


def _parse(command: str) -> list[_Segment]:
    lexer = shlex.shlex(command.replace("\n", ";"), posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    try:
        tokens = list(lexer)
    except ValueError as exc:
        raise UnparseableCommand(str(exc)) from exc
    segments: list[_Segment] = []
    argv: list[str] = []
    redirects: list[str] = []
    heredoc = False
    piped = False
    pending = ""  # 直前のリダイレクト演算子: "out"（書込先を記録）/ "in"（読み飛ばす）
    for token in tokens:
        if pending:
            if pending == "out":
                redirects.append(token)
            pending = ""
        elif _is_operator(token):
            if ">" in token:
                pending = "out"
            elif "<" in token:
                pending = "in"
                heredoc = heredoc or token.startswith("<<")
            else:
                if argv or redirects:
                    segments.append(_Segment(tuple(argv), tuple(redirects), heredoc, piped))
                argv, redirects, heredoc = [], [], False
                piped = token.startswith("|")
        elif not argv and not redirects and token in _RESERVED_WORDS:
            continue
        else:
            argv.append(token)
    if argv or redirects:
        segments.append(_Segment(tuple(argv), tuple(redirects), heredoc, piped))
    return segments


def split_segments(command: str) -> list[tuple[str, ...]]:
    return [segment.argv for segment in _parse(command) if segment.argv]


# --- ラッパー剥がし -----------------------------------------------------------


@dataclass(frozen=True)
class _WrapperSpec:
    flags: str = ""
    values: str = ""
    long_flags: frozenset[str] = frozenset()
    long_values: frozenset[str] = frozenset()
    positional: re.Pattern[str] | None = None


def _skip_options(args: Sequence[str], spec: _WrapperSpec) -> int | None:
    """オプションを読み飛ばした先の位置。読めないオプションがあれば None。"""
    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--":
            return i + 1
        if not arg.startswith("-") or arg == "-":
            return i
        if arg.startswith("--"):
            if "=" in arg or arg in spec.long_flags:
                i += 1
            elif arg in spec.long_values:
                i += 2
            else:
                return None
            continue
        step = _short_cluster_step(arg[1:], spec)
        if step is None:
            return None
        i += step
    return i


def _short_cluster_step(letters: str, spec: _WrapperSpec) -> int | None:
    for index, ch in enumerate(letters):
        if ch in spec.values:
            return 1 if index < len(letters) - 1 else 2
        if ch not in spec.flags:
            return None
    return 1


def _strip_with_spec(argv: tuple[str, ...], spec: _WrapperSpec) -> tuple[str, ...] | None:
    args = argv[1:]
    start = _skip_options(args, spec)
    if start is None or start > len(args):
        return None
    if spec.positional is not None:
        if start >= len(args) or not spec.positional.fullmatch(args[start]):
            return None
        start += 1
    return tuple(args[start:])


_ENV_FLAGS = frozenset({"-i", "-0", "-v", "-", "--ignore-environment", "--null", "--debug"})
_ENV_VALUE_OPTIONS = frozenset({"-u", "-C", "--unset", "--chdir"})


def _strip_env(argv: tuple[str, ...]) -> tuple[str, ...] | None:
    rest = argv[1:]
    i = 0
    while i < len(rest):
        arg = rest[i]
        if _ENV_ASSIGNMENT.match(arg) or arg in _ENV_FLAGS or ("=" in arg and arg[:2] == "--"):
            i += 1
        elif arg in _ENV_VALUE_OPTIONS:
            i += 2
        elif arg in {"-S", "--split-string"} and i + 1 < len(rest):
            try:
                return (*shlex.split(rest[i + 1]), *rest[i + 2 :])
            except ValueError:
                return None
        elif arg == "--":
            i += 1
            break
        elif arg.startswith("-"):
            return None
        else:
            break
    return tuple(rest[i:])


_DURATION = re.compile(r"\d+(\.\d+)?[smhd]?")
_WRAPPER_SPECS: dict[str, _WrapperSpec] = {
    "sudo": _WrapperSpec(
        flags="EnHSbkKPABis",
        values="ughpCDTUrtR",
        long_flags=frozenset(
            {
                "--non-interactive",
                "--stdin",
                "--login",
                "--shell",
                "--preserve-environment",
                "--set-home",
                "--background",
                "--reset-timestamp",
                "--askpass",
            }
        ),
        long_values=frozenset(
            {"--user", "--group", "--host", "--prompt", "--chdir", "--role", "--type"}
        ),
    ),
    "doas": _WrapperSpec(flags="nLs", values="uC"),
    "timeout": _WrapperSpec(
        flags="v",
        values="sk",
        long_flags=frozenset({"--foreground", "--preserve-status", "--verbose"}),
        long_values=frozenset({"--signal", "--kill-after"}),
        positional=_DURATION,
    ),
    "nice": _WrapperSpec(flags="0123456789", values="n", long_values=frozenset({"--adjustment"})),
    "ionice": _WrapperSpec(flags="t", values="cnpPu"),
    "stdbuf": _WrapperSpec(values="ioe"),
    "nohup": _WrapperSpec(),
    "command": _WrapperSpec(flags="p"),
    "exec": _WrapperSpec(flags="cl", values="a"),
    "time": _WrapperSpec(flags="pvaq", values="fo"),
}


def strip_wrappers(argv: Sequence[str]) -> tuple[str, ...]:
    current = tuple(argv)
    while True:
        while current and _ENV_ASSIGNMENT.match(current[0]):
            current = current[1:]
        if not current:
            return current
        name = posixpath.basename(current[0]).lower()
        if name == "env":
            stripped = _strip_env(current)
        elif name in _WRAPPER_SPECS:
            stripped = _strip_with_spec(current, _WRAPPER_SPECS[name])
        else:
            return current
        if stripped is None:
            return current
        current = stripped


# --- コマンド判定 -------------------------------------------------------------


def _assess_command_line(command: str) -> _Assessment:
    if _SUBSTITUTION.search(command):
        return _R2
    try:
        segments = _parse(command)
    except UnparseableCommand:
        return _R2
    assessment = _R0
    if _SQL_DESTRUCTIVE.search(command):
        assessment = _R2
    for match in _SQL_DELETE_FROM.finditer(command):
        if "where" not in match.group(0).lower():
            assessment = _R2
    for segment in segments:
        for target in segment.redirects:
            assessment = _max(assessment, _assess_path(target))
        assessment = _max(assessment, _assess_segment(segment))
    return assessment


def _assess_segment(segment: _Segment) -> _Assessment:
    argv = strip_wrappers(segment.argv)
    if not argv:
        return _R0
    name = posixpath.basename(argv[0]).lower()
    args = list(argv[1:])
    if _is_unanalyzable(name, args, segment):
        return _R2
    assessment = _assess_argv(name, args)
    for path in _written_paths(name, args):
        assessment = _max(assessment, _assess_path(path))
    return assessment


@dataclass(frozen=True)
class _Interpreter:
    inline_letters: str
    inline_long: frozenset[str]
    value_options: frozenset[str]


_SHELL_VALUE_OPTIONS = frozenset({"-o", "-O", "--rcfile", "--init-file"})
_SHELL_INTERPRETER = _Interpreter("c", frozenset(), _SHELL_VALUE_OPTIONS)
_INTERPRETERS: dict[str, _Interpreter] = {
    "sh": _SHELL_INTERPRETER,
    "bash": _SHELL_INTERPRETER,
    "zsh": _SHELL_INTERPRETER,
    "dash": _SHELL_INTERPRETER,
    "ksh": _SHELL_INTERPRETER,
    "fish": _SHELL_INTERPRETER,
    "python": _Interpreter("c", frozenset(), frozenset({"-W", "-X"})),
    "node": _Interpreter(
        "ep",
        frozenset({"--eval", "--print"}),
        frozenset({"-r", "--require", "--import", "--loader", "--experimental-loader"}),
    ),
    "perl": _Interpreter("eE", frozenset(), frozenset({"-I"})),
    "ruby": _Interpreter("e", frozenset(), frozenset({"-r", "-I"})),
}


def _interpreter_key(name: str) -> str | None:
    if re.fullmatch(r"(python|pypy)[\d.]*", name):
        return "python"
    return name if name in _INTERPRETERS else None


def _scan_interpreter(
    interpreter: _Interpreter, key: str, args: Sequence[str]
) -> tuple[bool, bool]:
    """(インラインコード指定の有無, スクリプト/モジュール引数の有無)。"""
    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--":
            return False, i + 1 < len(args)
        if not arg.startswith("-") or arg == "-":
            return False, arg != "-"
        if key == "python" and arg == "-m":
            return False, True
        if arg in interpreter.inline_long:
            return True, False
        if arg in interpreter.value_options:
            i += 2
            continue
        if not arg.startswith("--") and any(ch in interpreter.inline_letters for ch in arg[1:]):
            return True, False
        i += 1
    return False, False


def _is_unanalyzable(name: str, args: list[str], segment: _Segment) -> bool:
    if name in _ALWAYS_UNANALYZABLE:
        return True
    if name == "find":
        return any(a in _FIND_UNANALYZABLE for a in args)
    if name in _POWERSHELLS:
        return segment.heredoc or any(a.lower() in _POWERSHELL_INLINE for a in args)
    key = _interpreter_key(name)
    if key is None:
        return False
    inline, has_script = _scan_interpreter(_INTERPRETERS[key], key, args)
    # パイプ/ヒアドキュメントで標準入力から流し込まれたコードは中身を検査できない
    return inline or segment.heredoc or (segment.piped and not has_script)


def _short_flags(args: Sequence[str]) -> str:
    return "".join(a[1:] for a in args if a.startswith("-") and not a.startswith("--"))


def _written_paths(name: str, args: Sequence[str]) -> list[str]:
    if name == "dd":
        return [a.removeprefix("of=") for a in args if a.startswith("of=")]
    if name in {"sed", "perl"}:
        in_place = any(
            a.startswith("--in-place")
            or (a.startswith("-") and not a.startswith("--") and "i" in a)
            for a in args
        )
        if not in_place:
            return []
    elif name not in _PATH_WRITERS:
        return []
    paths: list[str] = []
    for arg in args:
        if arg.startswith("--") and "=" in arg:
            paths.append(arg.split("=", 1)[1])
        elif not arg.startswith("-"):
            paths.append(arg)
    return paths


# --- 副コマンド判定 -----------------------------------------------------------

_ToolHandler = Callable[[str, list[str], list[str]], _Assessment]


def _locate_sub(args: Sequence[str], value_options: frozenset[str]) -> tuple[int | None, bool]:
    """(副コマンドの位置, 読み飛ばし不能なオプションがあったか)。"""
    uncertain = False
    i = 0
    while i < len(args):
        arg = args[i]
        if not arg.startswith("-"):
            return i, uncertain
        if arg in value_options:
            i += 2
            continue
        if "=" not in arg:
            uncertain = True
        i += 1
    return None, uncertain


def _first_positional(args: Sequence[str], value_options: frozenset[str]) -> str:
    index, _ = _locate_sub(args, value_options)
    return args[index] if index is not None else ""


def _kubectl(sub: str, _sub_args: list[str], all_args: list[str]) -> _Assessment:
    if sub not in {"apply", "delete"}:
        return _R0
    return _R2 if any("prod" in a.lower() for a in all_args) else _R1


def _helm(sub: str, _sub_args: list[str], _all_args: list[str]) -> _Assessment:
    return _R2 if sub in {"upgrade", "install", "uninstall", "rollback"} else _R0


def _aws(sub: str, _sub_args: list[str], _all_args: list[str]) -> _Assessment:
    return _R2 if sub == "iam" else _R0


def _terraform(sub: str, _sub_args: list[str], _all_args: list[str]) -> _Assessment:
    return _R2 if sub in {"apply", "destroy"} else _R0


def _publisher(sub: str, _sub_args: list[str], _all_args: list[str]) -> _Assessment:
    return _R2 if sub == "publish" else _R0


_GH_VALUE_OPTIONS = frozenset({"-R", "--repo", "--hostname"})


def _gh(sub: str, sub_args: list[str], _all_args: list[str]) -> _Assessment:
    pair = (sub, _first_positional(sub_args, _GH_VALUE_OPTIONS))
    if pair == ("release", "create"):
        return _R2
    if pair in {("pr", "create"), ("pr", "merge")}:
        return _EXTERNAL
    return _R0


def _git(sub: str, sub_args: list[str], _all_args: list[str]) -> _Assessment:
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


_TOOLS: dict[str, tuple[frozenset[str], _ToolHandler]] = {
    "kubectl": (
        frozenset(
            {
                "-n",
                "--namespace",
                "--context",
                "--kubeconfig",
                "-s",
                "--server",
                "--cluster",
                "--user",
                "--token",
                "--as",
                "--as-group",
                "--request-timeout",
                "--certificate-authority",
                "--client-certificate",
                "--client-key",
                "-v",
                "--v",
            }
        ),
        _kubectl,
    ),
    "helm": (
        frozenset(
            {
                "-n",
                "--namespace",
                "--kube-context",
                "--kubeconfig",
                "--kube-apiserver",
                "--kube-token",
                "--kube-as-user",
                "--registry-config",
                "--repository-config",
                "--repository-cache",
            }
        ),
        _helm,
    ),
    "aws": (
        frozenset(
            {
                "--profile",
                "--region",
                "--endpoint-url",
                "--output",
                "--query",
                "--ca-bundle",
                "--color",
                "--cli-read-timeout",
                "--cli-connect-timeout",
            }
        ),
        _aws,
    ),
    "gh": (_GH_VALUE_OPTIONS, _gh),
    "git": (
        frozenset({"-C", "-c", "--work-tree", "--git-dir", "--namespace", "--config-env"}),
        _git,
    ),
    "terraform": (frozenset(), _terraform),
    "tofu": (frozenset(), _terraform),
    "npm": (
        frozenset(
            {
                "--registry",
                "--prefix",
                "-w",
                "--workspace",
                "--userconfig",
                "--globalconfig",
                "--cache",
                "--loglevel",
                "--otp",
                "--scope",
            }
        ),
        _publisher,
    ),
    "pnpm": (
        frozenset({"-C", "--dir", "--filter", "-F", "--workspace-dir", "--reporter", "--loglevel"}),
        _publisher,
    ),
    "yarn": (frozenset({"--cwd", "--registry"}), _publisher),
    "uv": (
        frozenset({"--directory", "--project", "--config-file", "--cache-dir", "--color"}),
        _publisher,
    ),
}


def _assess_tool(name: str, args: list[str]) -> _Assessment:
    value_options, handler = _TOOLS[name]
    index, uncertain = _locate_sub(args, value_options)
    if uncertain:
        # 値を取るか不明なオプションが副コマンド位置にあるので、どの位置が副コマンドでも
        # 危険側に倒れるよう全候補を判定する
        candidates = [i for i, a in enumerate(args) if not a.startswith("-")]
    else:
        candidates = [] if index is None else [index]
    assessment = _R0
    for i in candidates:
        assessment = _max(assessment, handler(args[i], args[i + 1 :], args))
    return assessment


def _assess_argv(name: str, args: list[str]) -> _Assessment:
    if name in _TOOLS:
        return _assess_tool(name, args)
    simple: dict[str, Callable[[list[str]], _Assessment]] = {
        "rm": _assess_rm,
        "chmod": _assess_chmod,
        "chown": _assess_chown,
        "twine": lambda a: _R2 if "upload" in a else _R0,
        "pip": lambda a: _R2 if "upload" in a else _R0,
        "gcloud": lambda a: _R2 if any("iam" in x for x in a) else _R0,
    }
    handler = simple.get(name)
    return handler(args) if handler else _R0


def _assess_rm(args: list[str]) -> _Assessment:
    flags = _short_flags(args)
    recursive = "r" in flags or "R" in flags or "--recursive" in args
    return _R2 if recursive else _R0


def _assess_chmod(args: list[str]) -> _Assessment:
    recursive = "R" in _short_flags(args) or "--recursive" in args
    return _R2 if recursive and any(a in {"777", "a+rwx", "o+w"} for a in args) else _R0


def _assess_chown(args: list[str]) -> _Assessment:
    return _R2 if "R" in _short_flags(args) or "--recursive" in args else _R0


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
        now: datetime,
    ) -> Decision:
        assessment = _assess(action)
        if assessment.risk == RiskRank.R2:
            code = "R2_REQUIRES_APPROVAL"
        elif assessment.external:
            code = "EXTERNAL_EFFECT_REQUIRES_APPROVAL"
        else:
            return Decision(True, assessment.risk, "ALLOWED", False, "approval not required")
        if unattended and _token_approves(token, token_scope, action_digest(action), now):
            return Decision(True, assessment.risk, "APPROVED_BY_TOKEN", False, "approved by token")
        message = "approval token required" if unattended else "human confirmation required"
        return Decision(False, assessment.risk, code, True, message)

    def authorize_tool(self, name: str) -> Decision:
        if name not in self._tool_allowlist and not self._tool_allowlist >= ALLOW_ALL:
            return Decision(
                False, RiskRank.R0, "TOOL_NOT_ALLOWED", False, f"tool not allowed: {name}"
            )
        return Decision(True, RiskRank.R0, "ALLOWED", False, "tool allowed")

    def authorize_command(self, argv: Sequence[str]) -> Decision:
        # フルパス指定は完全一致のみ許可する（偽装した同名バイナリを basename で通さない）
        name = argv[0] if argv else ""
        if not name or name not in self._command_allowlist:
            return Decision(
                False, RiskRank.R0, "COMMAND_NOT_ALLOWED", False, f"command not allowed: {name}"
            )
        return Decision(True, RiskRank.R0, "ALLOWED", False, "command allowed")

    def authorize_write(self, path: str, *, actor: Actor) -> Decision:
        risk = _assess_path(path).risk
        restricted = is_protected_path(path) or is_sensitive_path(path)
        if not restricted or actor == "human":
            return Decision(True, risk, "ALLOWED", False, "write allowed")
        if actor == "evolver":
            return Decision(False, risk, "PROTECTED_PATH", False, f"protected path: {path}")
        return Decision(
            False, risk, "PROTECTED_PATH_REQUIRES_APPROVAL", True, f"protected path: {path}"
        )


def _token_approves(
    token: ApprovalToken | None,
    token_scope: str | None,
    digest: str,
    now: datetime,
) -> bool:
    if token is None or token_scope is None:
        return False
    # AI 自己発行のトークンで承認をバイパスさせない
    if token.issued_by != "human":
        return False
    return token.is_valid_for(token_scope, digest, now)
