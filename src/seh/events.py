"""Hook イベントの正規化・判定・ホスト別表現。

D11: seh が存在する限り PreToolUse は fail-closed。fail-open は seh 不在時のシムだけが担う。
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import posixpath
import re
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import cast

from seh.authoring.lifecycle import native_stop, write_is_authorized, write_requires_plan
from seh.contracts import HostId
from seh.policy import (
    Action,
    Policy,
    UnparseableCommand,
    is_protected_path,
    is_sensitive_path,
    is_tool_config_path,
    split_segments,
    strip_wrappers,
)
from seh.redaction import contains_secret
from seh.trace import TraceWriter

KNOWN_EVENTS = frozenset({"PreToolUse", "PostToolUse", "SessionStart", "Stop"})

_GIT_DIFF_TIMEOUT_SECONDS = 10
_COMMAND_KEYS = ("command", "cmd", "script", "CommandLine")
_PATCH_PATH = re.compile(r"^\*\*\* (?:(?:Add|Update|Delete) File|Move to): (.+)$", re.MULTILINE)
_WRITE_TOOLS = frozenset(
    {
        "write",
        "edit",
        "multiedit",
        "notebookedit",
        "write_file",
        "edit_file",
        "write_to_file",
        "replace_file_content",
        "multi_replace_file_content",
        "apply_patch",
        "patch",
    }
)
_FORK_BOMB = re.compile(r":\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:")
_ROOT_TARGETS = frozenset(
    {"/", "//", "/.", "/*", "~", "~/", "~/*", "$HOME", "$HOME/", "$HOME/*", "${HOME}"}
)
_GIT_DIFF_FLAGS = ("--no-ext-diff", "--no-textconv")
_UNATTENDED_NOTE = "無人実行では承認できない"


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


def _walk_paths(value: object, under_path_key: bool, found: list[str]) -> None:
    if isinstance(value, dict):
        for key, child in cast("Mapping[object, object]", value).items():
            _walk_paths(
                child,
                isinstance(key, str) and ("path" in key.lower() or key.lower() == "targetfile"),
                found,
            )
    elif isinstance(value, list):
        for child in cast("list[object]", value):
            _walk_paths(child, under_path_key, found)
    elif isinstance(value, str):
        if "*** Begin Patch" in value:
            found.extend(m.strip() for m in _PATCH_PATH.findall(value) if m.strip())
        elif under_path_key and value:
            found.append(value)


def _collect_paths(args: Mapping[str, object]) -> tuple[str, ...]:
    found: list[str] = []
    _walk_paths(args, False, found)
    # `files` は path を含まないキー名だが、複数ファイルを渡す慣用名として明示的に拾う
    files = args.get("files")
    if isinstance(files, list):
        found.extend(f for f in cast("list[object]", files) if isinstance(f, str) and f)
    return tuple(found)


def _find_command(args: Mapping[str, object]) -> str | None:
    # 非文字列の値は無視せず不正入力として扱う（評価されない command を作らない）
    for key in _COMMAND_KEYS:
        value = _as_str(args.get(key), key)
        if value is not None:
            if value.lstrip().startswith("*** Begin Patch"):
                return None
            return value
    return None


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
    else:
        tool = _as_str(data.get("tool_name"), "tool_name")
        args = _as_dict(data.get("tool_input"), "tool_input")
        cwd = _as_str(data.get("cwd"), "cwd")
    if event == "PreToolUse" and tool is None:
        raise MalformedHookInput("tool is required")

    return HookInput(
        event=event,
        host=host,
        tool=tool,
        command=_find_command(args),
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
    args = _as_dict(call_dict.get("args"), "toolCall.args")
    command_cwd = _as_str(args.get("Cwd"), "toolCall.args.Cwd")
    return tool, args, command_cwd or cwd


def _is_catastrophic(command: str) -> bool:
    if _FORK_BOMB.search(command):
        return True
    for segment in split_segments(command):
        argv = strip_wrappers(segment)
        if not argv:
            continue
        name = posixpath.basename(argv[0])
        args = argv[1:]
        if name.startswith("mkfs"):
            return True
        if name == "dd" and any(a.startswith("of=/dev/") for a in args):
            return True
        if name == "rm" and _is_recursive_rm_of_root(args):
            return True
    return False


def _is_recursive_rm_of_root(args: Sequence[str]) -> bool:
    flags = "".join(a[1:] for a in args if a.startswith("-") and not a.startswith("--"))
    recursive = "r" in flags or "R" in flags or "--recursive" in args
    return recursive and any(a in _ROOT_TARGETS for a in args)


class SecretScanFailed(RuntimeError):
    pass


def _is_git(argv: Sequence[str]) -> bool:
    return bool(argv) and posixpath.basename(argv[0]) == "git"


def _is_commit_all(args: Sequence[str]) -> bool:
    return any(
        a == "--all" or (a.startswith("-") and not a.startswith("--") and "a" in a) for a in args
    )


def _git_output(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        errors="replace",
        timeout=_GIT_DIFF_TIMEOUT_SECONDS,
        check=False,
    )


def _diff_text(cwd: Path, *args: str) -> str:
    result = _git_output(cwd, "diff", *args, *_GIT_DIFF_FLAGS)
    if result.returncode != 0:
        raise SecretScanFailed(f"git diff exited with {result.returncode}")
    return result.stdout


def _diffs_have_secret(cwd: Path, *, include_worktree: bool) -> bool:
    texts = [_diff_text(cwd, "--cached")]
    if include_worktree:
        has_head = _git_output(cwd, "rev-parse", "--verify", "-q", "HEAD").returncode == 0
        texts.append(_diff_text(cwd, "HEAD") if has_head else _diff_text(cwd))
    return any(contains_secret(text) for text in texts)


def _evaluate_commit(inp: HookInput, segments: list[tuple[str, ...]]) -> HookOutcome | None:
    commits = [s for s in segments if _is_git(s) and "commit" in s[1:]]
    if not commits:
        return None
    includes_worktree = any(_is_commit_all(c[1:]) for c in commits) or any(
        _is_git(s) and "add" in s[1:] for s in segments
    )
    try:
        has_secret = _diffs_have_secret(inp.cwd, include_worktree=includes_worktree)
    except (SecretScanFailed, subprocess.SubprocessError, OSError) as e:
        return HookOutcome(
            HookDecision.DENY,
            "SECRET_SCAN_FAILED",
            f"commit 前の秘密情報スキャンに失敗したためブロックしました: {type(e).__name__}",
        )
    if has_secret:
        return HookOutcome(
            HookDecision.DENY,
            "SECRET_IN_STAGED_DIFF",
            "commit 対象の差分に秘密情報の疑いがあるため commit をブロックしました",
        )
    changes_dir = any(posixpath.basename(s[0]) in {"cd", "pushd"} for s in segments) or any(
        a == "-C" or a.startswith(("-C", "--git-dir", "--work-tree"))
        for c in commits
        for a in c[1:]
    )
    if changes_dir:
        return HookOutcome(
            HookDecision.ASK,
            "COMMIT_OUTSIDE_CWD",
            "cwd 外のリポジトリへの commit の可能性があり、秘密スキャンできません。承認が必要です",
        )
    return None


def _evaluate_command(inp: HookInput, command: str, policy: Policy) -> HookOutcome:
    try:
        segments = [strip_wrappers(s) for s in split_segments(command)]
    except UnparseableCommand:
        return HookOutcome(
            HookDecision.DENY, "UNPARSEABLE_COMMAND", "コマンドを解析できないためブロックしました"
        )
    if _is_catastrophic(command):
        return HookOutcome(
            HookDecision.DENY, "CATASTROPHIC_COMMAND", "破壊的コマンドはブロックされました"
        )
    commit_outcome = _evaluate_commit(inp, [s for s in segments if s])
    if commit_outcome is not None:
        return commit_outcome
    decision = policy.authorize(Action("command", command), unattended=False, now=datetime.now(UTC))
    if decision.allowed:
        return _ALLOW
    return HookOutcome(HookDecision.ASK, decision.reason_code, decision.message)


def _evaluate_path(path: str, cwd: Path) -> HookOutcome:
    name = posixpath.basename(path)
    if is_sensitive_path(path):
        return HookOutcome(HookDecision.DENY, "SENSITIVE_FILE", f"機密ファイルの編集は禁止: {name}")
    if is_tool_config_path(path):
        return HookOutcome(
            HookDecision.DENY,
            "PROTECTED_TOOL_CONFIG",
            f"Linter/Formatter/型チェッカー設定の編集は禁止: {name}",
        )
    if is_protected_path(path, root=cwd):
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
    if inp.command is not None:
        command_outcome = _evaluate_command(inp, inp.command, policy)
        if command_outcome.decision != HookDecision.ALLOW:
            return command_outcome
    if inp.paths:
        outcome = _evaluate_paths(inp)
        if outcome.decision != HookDecision.ALLOW:
            return outcome
        if (
            (inp.cwd / ".harness").is_dir()
            and (inp.tool or "").lower() in _WRITE_TOOLS
            and write_requires_plan(inp.cwd, inp.paths)
            and not write_is_authorized(inp.cwd, inp.paths)
        ):
            return HookOutcome(
                HookDecision.DENY,
                "AUTHORING_PLAN_REQUIRED",
                "先に seh author で計画と評価を行ってください",
            )
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
        # ADR-0003 で確認済みの値は deny のみ。未確認の ask は出さない
        body = {"decision": HookDecision.DENY.value, "reason": message}
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
    unattended: bool,
) -> tuple[int, str, str]:
    if event not in KNOWN_EVENTS:
        return _fail_closed(host, "UNKNOWN_EVENT", f"未知の Hook イベント: {event}")
    blocking = event == "PreToolUse"
    try:
        inp = parse_hook_input(event, host, payload)
        if event == "SessionStart":
            outputs = [out for h in SESSION_START_HANDLERS if (out := h(inp))]
            return 0, "\n".join(outputs), ""
        if event == "Stop" and (inp.cwd / ".harness").is_dir():
            session = inp.raw.get("session_id")
            status = native_stop(inp.cwd, session if isinstance(session, str) else str(inp.cwd))
            if status.needs_eval:
                message = "NEEDS_EVAL: 未評価の Authoring 変更があります: " + ", ".join(
                    status.paths
                )
                if status.block and host == HostId.CLAUDE:
                    return (
                        0,
                        json.dumps({"decision": "block", "reason": message}, ensure_ascii=False),
                        "",
                    )
                return 0, "", message
        outcome = evaluate(inp, policy=policy)
        if unattended and outcome.decision == HookDecision.ASK:
            outcome = HookOutcome(
                HookDecision.DENY, outcome.reason_code, f"{_UNATTENDED_NOTE}: {outcome.message}"
            )
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
