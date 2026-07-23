# just 生成モジュール

優先順位: 2位。just は存在時プライマリランナーであることが多いため、make より優先して採用。

## detect

ツール存在確認: `justfile` / `.justfile` の存在 + `command -v just`。
実在レシピ問い合わせ: `just --list` で全レシピを決定論的に取得。

## ci-commands

レシピ名を `just --list` 結果から判定。慣例レシピ名を優先:

- `CI_CHECK_CMD`: `just ci`(ci レシピ存在時)→ `just check` → なければ `just test` + `just lint` の合成
- `CI_FIX_CMD`: `just fix`(fix レシピ存在時)→ `just fmt`

## hook-template

### PreToolUse: CIゲート(git commit 前)

matcher: `Bash`

```sh
input=$(cat); case "$input" in *'git commit'*) cache='/tmp/.claude_ci_cache'; if [ -f "$cache" ] && [ $(($(date +%s) - $(cat "$cache"))) -lt 60 ]; then exit 0; fi; output=$(just ci 2>&1); rc=$?; if [ $rc -ne 0 ]; then echo "$output" | tail -30 >&2; echo 'BLOCKED: just ci failed. Fix before committing.' >&2; exit 2; fi; date +%s > "$cache"; exit 0;; esac; exit 0
```

timeout: 300。`just ci` は検出した代表レシピに置換。
