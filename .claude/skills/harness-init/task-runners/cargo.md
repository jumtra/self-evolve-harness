# cargo 生成モジュール

優先順位: 4位。Rust プロジェクトで採用。

## detect

ツール: `Cargo.toml` の存在。
実在タスク問い合わせ: `cargo metadata --no-deps` でクレート構造を取得。

## ci-commands

cargo 標準サブコマンドを組み合わせ:

- `CI_CHECK_CMD`: `cargo fmt --check && cargo clippy -- -D warnings && cargo test`（fmt→clippy→test）
- `CI_FIX_CMD`: `cargo fmt`

## hook-template

### PreToolUse: CIゲート（git commit 前）

matcher: `Bash`

```sh
input=$(cat); case "$input" in *'git commit'*) cache='/tmp/.claude_ci_cache'; if [ -f "$cache" ] && [ $(($(date +%s) - $(cat "$cache"))) -lt 60 ]; then exit 0; fi; output=$(cargo fmt --check && cargo clippy -- -D warnings && cargo test 2>&1); rc=$?; if [ $rc -ne 0 ]; then echo "$output" | tail -30 >&2; echo 'BLOCKED: cargo checks failed. Fix before committing.' >&2; exit 2; fi; date +%s > "$cache"; exit 0;; esac; exit 0
```

timeout: 300。
