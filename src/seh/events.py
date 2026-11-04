"""Hook イベントの正規化・判定・ホスト別表現。

D11: seh が存在する限り PreToolUse は fail-closed。fail-open は seh 不在時のシムだけが担う。
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import posixpath
import re
import shlex
import subprocess
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from fnmatch import fnmatchcase
from pathlib import Path
from typing import cast

from seh.contracts import HostId
from seh.policy import Action, Policy, is_protected_path
from seh.redaction import contains_secret
from seh.trace import TraceWriter

KNOWN_EVENTS = frozenset({"PreToolUse", "PostToolUse", "SessionStart", "Stop"})

_BASH_TOOLS = frozenset({"bash", "shell", "run_command", "run_shell_command", "exec_command"})
_GIT_DIFF_TIMEOUT_SECONDS = 10

_SENSITIVE_NAME_GLOBS = (".env", ".env.*", "*.pem", "*.key", "*credential*", "*secret*")
_TOOL_CONFIG_GLOBS = (
    ".eslintrc*",
    "eslint.config.*",
    ".prettierrc*",
    "prettier.config.*",
    "biome.json*",
    "ruff.toml",
    ".ruff.toml",
    "pyrightconfig.json",
    "mypy.ini",
    ".flake8",
    "tsconfig*.json",
    ".golangci.*",
    "rustfmt.toml",
    "clippy.toml",
    ".editorconfig",
)

_FORK_BOMB = re.compile(r":\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:")
_SEGMENT_SPLIT = re.compile(r"[;&|\n]+")
_ROOT_TARGETS = frozenset({"/", "/*", "~", "~/", "~/*", "$HOME", "$HOME/", "$HOME/*", "${HOME}"})
_WRAPPERS = frozenset({"sudo", "env", "nohup", "time", "command", "exec"})


class MalformedHookInput(ValueError):
    pass


class HookDecision(StrEnum):
    ALLOW = "allow"
    ASK = "ask"
    DENY = "deny"


@dataclass(frozen=True)
class HookInput:
    event: str
    host: HostId
    tool: str | None
    command: str | None
    paths: tuple[str, ...]
    cwd: Path
    raw: Mapping[str, object]


@dataclass(frozen=True)
class HookOutcome:
    decision: HookDecision
    reason_code: str
    message: str


# 後続タスク（メモリ想起・doctor 通知）が登録する拡張点。各ハンドラは stdout に出す文字列を返す。
SESSION_START_HANDLERS: list[Callable[[HookInput], str | None]] = []

_ALLOW = HookOutcome(HookDecision.ALLOW, "ALLOWED", "")


def _as_str(value: object, what: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise MalformedHookInput(f"{what} must be a string")
    return value


def _as_dict(value: object, what: str) -> Mapping[str, object]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise MalformedHookInput(f"{what} must be an object")
    return cast("Mapping[str, object]", value)


def _collect_paths(args: Mapping[str, object]) -> tuple[str, ...]:
    paths: list[str] = []
    for key in ("file_path", "filePath", "path"):
        value = _as_str(args.get(key), key)
        if value:
            paths.append(value)
    edits = args.get("edits")
    if edits is not None:
        if not isinstance(edits, list):
            raise MalformedHookInput("edits must be an array")
        for edit in edits:
            value = _as_str(_as_dict(edit, "edit").get("file_path"), "edits[].file_path")
            if value:
                paths.append(value)
    return tuple(paths)


def parse_hook_input(event: str, host: HostId, payload: bytes) -> HookInput:
    try:
        raw = json.loads(payload)
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise MalformedHookInput(f"invalid JSON: {e}") from e
    if not isinstance(raw, dict):
        raise MalformedHookInput("payload must be a JSON object")
    data: Mapping[str, object] = raw
    needs_tool = event in {"PreToolUse", "PostToolUse"}

    if host == HostId.ANTIGRAVITY:
        tool, args, cwd = _antigravity_fields(data, needs_tool)
    elif host == HostId.OPENCODE:
        tool = _as_str(data.get("tool"), "tool")
        args = _as_dict(data.get("args"), "args")
        cwd = _as_str(data.get("cwd"), "cwd")
        if needs_tool and tool is None:
            raise MalformedHookInput("tool is required")
    else:
        tool = _as_str(data.get("tool_name"), "tool_name")
        args = _as_dict(data.get("tool_input"), "tool_input")
        cwd = _as_str(data.get("cwd"), "cwd")

    return HookInput(
        event=event,
        host=host,
        tool=tool,
        command=_as_str(args.get("command"), "command"),
        paths=_collect_paths(args),
        cwd=Path(cwd) if cwd else Path.cwd(),
        raw=data,
    )


def _antigravity_fields(
    data: Mapping[str, object], needs_tool: bool
) -> tuple[str | None, Mapping[str, object], str | None]:
    workspaces = data.get("workspacePaths")
    cwd = None
    if isinstance(workspaces, list) and workspaces:
        cwd = _as_str(workspaces[0], "workspacePaths[0]")
    call = data.get("toolCall")
    if not needs_tool and call is None:
        return None, {}, cwd
    call_dict = _as_dict(call, "toolCall")
    tool = _as_str(call_dict.get("name"), "toolCall.name")
    if tool is None or cwd is None:
        raise MalformedHookInput("toolCall.name and workspacePaths[0] are required")
    return tool, _as_dict(call_dict.get("args"), "toolCall.args"), cwd


def _segments(command: str) -> list[list[str]]:
    result: list[list[str]] = []
    for part in _SEGMENT_SPLIT.split(command):
        try:
            argv = shlex.split(part)
        except ValueError:
            argv = part.split()
        while argv and argv[0] in _WRAPPERS:
            argv = argv[1:]
        if argv:
            result.append(argv)
    return result


def _is_catastrophic(command: str) -> bool:
    if _FORK_BOMB.search(command):
        return True
    for argv in _segments(command):
        name = posixpath.basename(argv[0])
        args = argv[1:]
        if name.startswith("mkfs"):
            return True
        if name == "dd" and any(a.startswith("of=/dev/") for a in args):
            return True
        if name == "rm" and _is_recursive_rm_of_root(args):
            return True
    return False


def _is_recursive_rm_of_root(args: list[str]) -> bool:
    flags = "".join(a[1:] for a in args if a.startswith("-") and not a.startswith("--"))
    recursive = "r" in flags or "R" in flags or "--recursive" in args
    return recursive and any(a in _ROOT_TARGETS for a in args)


def _is_git_commit(command: str) -> bool:
    return any(posixpath.basename(a[0]) == "git" and "commit" in a[1:] for a in _segments(command))


def _staged_diff_has_secret(cwd: Path) -> bool:
    # 失敗・タイムアウトは例外のまま伝播させ、run_hook の fail-closed に任せる
    result = subprocess.run(
        ["git", "diff", "--cached"],
        cwd=cwd,
        capture_output=True,
        text=True,
        errors="replace",
        timeout=_GIT_DIFF_TIMEOUT_SECONDS,
        check=False,
    )
    return contains_secret(result.stdout)


def _evaluate_command(inp: HookInput, command: str, policy: Policy) -> HookOutcome:
    if _is_catastrophic(command):
        return HookOutcome(
            HookDecision.DENY, "CATASTROPHIC_COMMAND", "破壊的コマンドはブロックされました"
        )
    if _is_git_commit(command) and _staged_diff_has_secret(inp.cwd):
        return HookOutcome(
            HookDecision.DENY,
            "SECRET_IN_STAGED_DIFF",
            "staged 差分に秘密情報の疑いがあるため commit をブロックしました",
        )
    decision = policy.authorize(Action("command", command), unattended=False, now=datetime.now(UTC))
    if decision.allowed:
        return _ALLOW
    if decision.reason_code == "R2_REQUIRES_APPROVAL":
        return HookOutcome(
            HookDecision.ASK, "R2_REQUIRES_APPROVAL", "高リスク操作です。承認が必要です"
        )
    return HookOutcome(
        HookDecision.ASK, "EXTERNAL_EFFECT", "外部作用のある操作です。承認が必要です"
    )


def _matches(name: str, globs: tuple[str, ...]) -> bool:
    lowered = name.lower()
    return any(fnmatchcase(lowered, g) for g in globs)


def _relative_to_cwd(path: str, cwd: Path) -> str:
    candidate = Path(path)
    if candidate.is_absolute():
        try:
            return candidate.relative_to(cwd).as_posix()
        except ValueError:
            return path
    return path


def _evaluate_path(path: str, cwd: Path) -> HookOutcome:
    name = posixpath.basename(path)
    if _matches(name, _SENSITIVE_NAME_GLOBS):
        return HookOutcome(HookDecision.DENY, "SENSITIVE_FILE", f"機密ファイルの編集は禁止: {name}")
    if _matches(name, _TOOL_CONFIG_GLOBS):
        return HookOutcome(
            HookDecision.DENY,
            "PROTECTED_TOOL_CONFIG",
            f"Linter/Formatter/型チェッカー設定の編集は禁止: {name}",
        )
    if is_protected_path(_relative_to_cwd(path, cwd)):
        return HookOutcome(HookDecision.ASK, "PROTECTED_PATH", f"保護パスの編集です: {path}")
    return _ALLOW


def _evaluate_paths(inp: HookInput) -> HookOutcome:
    outcomes = [_evaluate_path(p, inp.cwd) for p in inp.paths]
    for wanted in (HookDecision.DENY, HookDecision.ASK):
        for outcome in outcomes:
            if outcome.decision == wanted:
                return outcome
    return _ALLOW


def evaluate(inp: HookInput, *, policy: Policy) -> HookOutcome:
    if inp.event != "PreToolUse":
        return _ALLOW
    if inp.command is not None and (inp.tool or "").lower() in _BASH_TOOLS:
        return _evaluate_command(inp, inp.command, policy)
    if inp.paths:
        return _evaluate_paths(inp)
    return _ALLOW


def render_outcome(outcome: HookOutcome, host: HostId) -> tuple[int, str, str]:
    decision = outcome.decision
    if decision == HookDecision.ALLOW:
        return 0, "", ""
    message = outcome.message
    if host == HostId.CLAUDE:
        if decision == HookDecision.DENY:
            return 2, "", message
        body = {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "ask",
                "permissionDecisionReason": message,
            }
        }
        return 0, json.dumps(body, ensure_ascii=False), ""
    if host == HostId.ANTIGRAVITY:
        body = {"decision": decision.value, "reason": message}
        return 0, json.dumps(body, ensure_ascii=False), ""
    if host == HostId.CODEX and decision == HookDecision.ASK:
        return 2, "", f"承認が必要: {message}"
    return 2, "", message


def _warn_pass(message: str) -> tuple[int, str, str]:
    return 0, "", f"警告: {message}"


def _fail_closed(host: HostId, code: str, message: str) -> tuple[int, str, str]:
    return render_outcome(HookOutcome(HookDecision.DENY, code, message), host)


def _emit_trace(trace: TraceWriter | None, inp: HookInput, outcome: HookOutcome) -> None:
    if trace is None:
        return
    data: dict[str, object] = {
        "event": inp.event,
        "host": inp.host.value,
        "tool": inp.tool,
        "decision": outcome.decision.value,
        "reason_code": outcome.reason_code,
    }
    if inp.command is not None:
        data["command_sha256"] = hashlib.sha256(inp.command.encode("utf-8")).hexdigest()
    # trace は観測用。書けなくても判定結果を変えない
    with contextlib.suppress(OSError):
        trace.emit("hook.decision", run_id="hook", data=data)


def run_hook(
    event: str,
    host: HostId,
    payload: bytes,
    *,
    policy: Policy,
    trace: TraceWriter | None,
) -> tuple[int, str, str]:
    if event not in KNOWN_EVENTS:
        return _fail_closed(host, "UNKNOWN_EVENT", f"未知の Hook イベント: {event}")
    blocking = event == "PreToolUse"
    try:
        inp = parse_hook_input(event, host, payload)
        if event == "SessionStart":
            outputs = [out for h in SESSION_START_HANDLERS if (out := h(inp))]
            return 0, "\n".join(outputs), ""
        outcome = evaluate(inp, policy=policy)
        _emit_trace(trace, inp, outcome)
        return render_outcome(outcome, host)
    except MalformedHookInput as e:
        if blocking:
            return _fail_closed(host, "MALFORMED_INPUT", f"Hook 入力が不正です: {e}")
        return _warn_pass(f"Hook 入力が不正です: {e}")
    except Exception as e:  # fail-closed のため意図的に全例外を捕捉する
        if blocking:
            return _fail_closed(host, "INTERNAL_ERROR", f"Hook 内部エラー: {type(e).__name__}")
        return _warn_pass(f"Hook 内部エラー: {type(e).__name__}")
