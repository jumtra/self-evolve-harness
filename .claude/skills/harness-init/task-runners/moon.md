# moon 生成モジュール

優先順位: 1位（最高）。moon 検出時は代表CIコマンドとして採用。

## detect

ツール存在確認: `command -v moon` または `.moon/` ディレクトリの存在。
実在タスク問い合わせ: `moon query tasks` で全プロジェクト × 全タスク（`<project>:<task>` 形式）を取得。

## ci-commands

集合タスクが存在するか `moon query tasks` の結果から判定:

- `CI_CHECK_CMD`: `moon ci :check`（`:check` 集合タスク存在時）。なければ `moon run :test` + `:typecheck` + `:lint` を合成
- `CI_FIX_CMD`: `moon run :fix`（`:fix` 存在時）

monorepo の per-package 実行: `moon run <project>:<task>` を記録（ドキュメント用）。

## hook-template

### PreToolUse: CIゲート（git commit 前）

matcher: `Bash`

```sh
input=$(cat); case "$input" in *'git commit'*) cache='/tmp/.claude_ci_cache'; if [ -f "$cache" ] && [ $(($(date +%s) - $(cat "$cache"))) -lt 60 ]; then exit 0; fi; output=$(moon ci :check 2>&1); rc=$?; if [ $rc -ne 0 ]; then echo "$output" | tail -30 >&2; echo 'BLOCKED: moon ci :check failed. Fix before committing.' >&2; exit 2; fi; date +%s > "$cache"; exit 0;; esac; exit 0
```

timeout: 300
