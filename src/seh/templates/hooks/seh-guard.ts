// OpenCode plugin: tool.execute.before で seh hook に判定を委譲する（ADR-0003）。
import { spawnSync } from "node:child_process"

export const SehGuard = async ({ directory }: { directory: string }) => ({
  "tool.execute.before": async (input: { tool: string }, output: { args: unknown }) => {
    const payload = JSON.stringify({ tool: input.tool, args: output.args, cwd: directory })
    const result = spawnSync("seh", ["hook", "PreToolUse", "--host", "opencode"], {
      input: payload,
      encoding: "utf-8",
      timeout: 10000,
    })
    const error = result.error as NodeJS.ErrnoException | undefined
    if (error?.code === "ENOENT") {
      console.warn("警告: seh が未導入のため Hook を通過させます")
      return
    }
    // タイムアウト(error.code === ETIMEDOUT)・シグナル終了・非0 はすべてブロック
    if (error || result.signal || result.status !== 0) {
      throw new Error(result.stderr || "seh hook によりブロックされました")
    }
  },
})
