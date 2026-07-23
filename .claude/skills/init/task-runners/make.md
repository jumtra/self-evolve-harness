# make 生成モジュール

優先順位: 3位。

## detect

ツール存在確認: `Makefile` / `makefile` / `GNUmakefile` の存在。
実在ターゲット問い合わせ: `make -p` で全ターゲット一覧を取得（`.PHONY` 等を除外）。

## ci-commands

ターゲット名を `make -p` 結果から判定。慣例ターゲット名を優先:

- `CI_CHECK_CMD`: `make ci`（ci ターゲット存在時）→ なければ `make test lint typecheck`
- `CI_FIX_CMD`: `make fix`（fix ターゲット存在時）

## hook-template

### PreToolUse: CIゲート（git commit 前）

matcher: `Bash`

```sh
input=$(cat); case "$input" in *'git commit'*) cache='/tmp/.claude_ci_cache'; if [ -f "$cache" ] && [ $(($(date +%s) - $(cat "$cache"))) -lt 60 ]; then exit 0; fi; output=$(make ci 2>&1); rc=$?; if [ $rc -ne 0 ]; then echo "$output" | tail -30 >&2; echo 'BLOCKED: make ci failed. Fix before committing.' >&2; exit 2; fi; date +%s > "$cache"; exit 0;; esac; exit 0
```

timeout: 300。`make ci` は検出した代表ターゲットに置換。
