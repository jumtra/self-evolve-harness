"""Render host hooks; absent seh is the only fail-open condition."""

from __future__ import annotations

import json
from collections.abc import Mapping

from seh.contracts import ChangeAction, HostId, PlannedChange


def render_hooks(
    host: HostId, permissions: Mapping[str, str] | None = None
) -> tuple[PlannedChange, ...]:
    permissions = permissions or {}
    owner = f"host:{host.value}"
    if host == HostId.OPENCODE:
        path = ".opencode/plugins/seh-guard.ts"
        content = """export const SehGuard = async ({ directory }: { directory: string }) => ({
  "tool.execute.before": async (input: { tool: string }, output: { args: unknown }) => {
    const cmd = "if ! command -v seh >/dev/null 2>&1; then " +
      "echo 'seh not installed' >&2; exit 0; fi; " +
      "exec seh hook PreToolUse --host opencode";
    const proc = Bun.spawnSync(["sh", "-c", cmd], {
      stdin: new TextEncoder().encode(JSON.stringify({
        tool: input.tool, args: output.args, cwd: directory
      })), cwd: directory, stdout: "pipe", stderr: "pipe"
    });
    if (proc.exitCode !== 0) throw new Error(new TextDecoder().decode(proc.stderr));
    if (proc.stderr.length) console.warn(new TextDecoder().decode(proc.stderr));
  },
});
"""
    else:
        paths = {
            HostId.CLAUDE: ".claude/settings.json",
            HostId.CODEX: ".codex/hooks.json",
            HostId.ANTIGRAVITY: ".agents/hooks.json",
        }
        path = paths[host]
        hooks: dict[str, object] = {}
        for event in ("PreToolUse", "PostToolUse", "SessionStart", "Stop"):
            command = (
                "if ! command -v seh >/dev/null 2>&1; then "
                "echo 'seh not installed; hook bypassed' >&2; exit 0; fi; "
            )
            invocation = f"seh hook {event} --host {host.value}"
            if event == "PreToolUse" and host == HostId.CODEX:
                command += f'{invocation}; status=$?; if [ "$status" -ne 0 ]; then exit 2; fi'
            elif event == "PreToolUse" and host == HostId.ANTIGRAVITY:
                command += (
                    f"result=$({invocation}); status=$?; "
                    'if [ "$status" -ne 0 ]; then '
                    'printf \'%s\\n\' \'{"decision":"deny","reason":"seh hook failed"}\'; '
                    "exit 0; fi; printf '%s' \"$result\""
                )
            else:
                command += f"exec {invocation}"
            handler: dict[str, object] = {"type": "command", "command": command}
            if host == HostId.CLAUDE and event == "PreToolUse":
                handler["onFailure"] = "block"
            if host == HostId.ANTIGRAVITY and event in ("SessionStart", "Stop"):
                hooks[event] = [handler]
            else:
                hooks[event] = [{"hooks": [handler]}]
        config: dict[str, object] = (
            {"seh": hooks} if host == HostId.ANTIGRAVITY else {"hooks": hooks}
        )
        if host == HostId.CLAUDE and permissions:
            names = {"read": ("Read",), "write": ("Write", "Edit"), "bash": ("Bash",)}
            rules: dict[str, list[str]] = {}
            for name, action in permissions.items():
                rules.setdefault(action, []).extend(names[name])
            config["permissions"] = rules
        content = json.dumps(config, indent=2) + "\n"
    changes = [PlannedChange(path, ChangeAction.UPDATE, content.encode(), "hook", owner)]
    if host == HostId.OPENCODE and permissions:
        names = {"read": "read", "write": "edit", "bash": "bash"}
        config = {"permission": {names[k]: v for k, v in permissions.items()}}
        changes.append(
            PlannedChange(
                "opencode.json",
                ChangeAction.UPDATE,
                (json.dumps(config, indent=2) + "\n").encode(),
                "permissions",
                owner,
            )
        )
    return tuple(changes)
