# 汎用タスクランナー検出モジュール

優先順位: 最低(フォールバック)。moon/just/make/cargo/npm-scripts のいずれも未検出時に採用。

## detect

1. タスクランナー設定ファイルを探索: `Taskfile.yml`(go-task) / `build.gradle`・`gradlew`(gradle) /
   `pom.xml`(maven) / `Rakefile`(rake) / `mix.exs`(mix) 等
2. ツール存在確認: `command -v <tool>`(gradlew のようなラッパースクリプトはファイル存在で可)
3. list 系コマンドで実在タスクを決定論的に列挙: `task --list-all` / `./gradlew tasks` /
   `rake -T` / `mix help` 等。**列挙コマンドが用意できないランナーはユーザーにタスク名を確認する**

## ci-commands

列挙結果から慣例タスク名を対応付ける:

- `CI_CHECK_CMD`: `ci`・`check` 相当タスク → なければ `test` + `lint` 相当の合成
- `CI_FIX_CMD`: `fix`・`format` 相当タスク
- **該当タスクがなければユーザーに確認する(推測で決めない)**

## hook-template

### PreToolUse: CIゲート(git commit 前)

matcher: `Bash`

```sh
input=$(cat); case "$input" in *'git commit'*) cache='/tmp/.claude_ci_cache'; if [ -f "$cache" ] && [ $(($(date +%s) - $(cat "$cache"))) -lt 60 ]; then exit 0; fi; output=$(<CI_CHECK_CMD> 2>&1); rc=$?; if [ $rc -ne 0 ]; then echo "$output" | tail -30 >&2; echo 'BLOCKED: <CI_CHECK_CMD> failed. Fix before committing.' >&2; exit 2; fi; date +%s > "$cache"; exit 0;; esac; exit 0
```

timeout: 300。`<CI_CHECK_CMD>` は検出結果に置換。
