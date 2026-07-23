# npm-scripts 生成モジュール

優先順位: 5位。Node プロジェクトで moon/just/make が未検出時に採用。

## detect

ツール: `package.json` の `scripts` フィールドを `node -e` で構造化パース。
パッケージマネージャ検出（優先順）:

1. `package.json` の `packageManager` フィールド（明示宣言・最優先）
2. lockfile: `pnpm-lock.yaml` → pnpm / `yarn.lock` → yarn / `bun.lockb`・`bun.lock` → bun / `package-lock.json` → npm
3. いずれもなければ npm

## ci-commands

`scripts` に存在するスクリプト名から導出:

- `CI_CHECK_CMD`: `<pm> run ci`（ci 存在時）→ なければ `<pm> run test` + `<pm> run lint` + `<pm> run typecheck`
- `CI_FIX_CMD`: `<pm> run fix`（fix 存在時）→ なければ `<pm> run lint --fix` 等

`<pm>` は検出したパッケージマネージャ（npm/pnpm/bun/yarn）。

## hook-template

### PreToolUse: CIゲート（git commit 前）

matcher: `Bash`

```sh
input=$(cat); case "$input" in *'git commit'*) cache='/tmp/.claude_ci_cache'; if [ -f "$cache" ] && [ $(($(date +%s) - $(cat "$cache"))) -lt 60 ]; then exit 0; fi; output=$(npm run ci 2>&1); rc=$?; if [ $rc -ne 0 ]; then echo "$output" | tail -30 >&2; echo 'BLOCKED: npm run ci failed. Fix before committing.' >&2; exit 2; fi; date +%s > "$cache"; exit 0;; esac; exit 0
```

timeout: 300。`npm run` は検出したパッケージマネージャの実行形（`pnpm run` / `yarn` / `bun run` / `npm run`）に、`ci` は検出結果に置換。
