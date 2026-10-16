# 言語非依存フック雛形

`/harness-init` が常に含める言語非依存の安全装置フック。検出した言語・タスクランナーのフックは `languages/` `task-runners/` から合成して追加する。

## フック入力の受け取り方（共通規約）

Claude Code はフックにツール入力を**環境変数では渡さない**。入力は stdin の JSON
（`tool_input.file_path` / `tool_input.command` 等）で渡される。外部ツール（jq 等）への
依存を避けるため、抽出は POSIX シェルの組み込み（パラメータ展開・case）のみで行う:

```sh
# file_path 抽出の共通イディオム（jq 不使用・組み込みのみ。コンパクト/スペース入り JSON 両対応）
input=$(cat); f=${input#*\"file_path\":\"}; [ "$f" = "$input" ] && f=${input#*\"file_path\": \"}; [ "$f" = "$input" ] && exit 0; file=${f%%\"*}
```

- ブロック時のメッセージは **stderr**（`>&2`）に出して `exit 2`（exit 2 で Claude に渡るのは stderr）
- ブロックは **PreToolUse のみ**で行う。PostToolUse はツール実行後のため exit 2 でもブロックできない
- Bash コマンドの判定は file_path 抽出をせず、stdin 全体への `case` サブストリングマッチで行う

## PreToolUse: 破壊的コマンドブロック

matcher: `Bash`

```sh
input=$(cat); case "$input" in *'rm -rf /'*|*'rm -rf ~'*|*'sudo '*|*'> /dev/sda'*) echo 'BLOCKED: destructive command' >&2; exit 2;; esac; exit 0
```

## PreToolUse: 機密ファイル編集ブロック

matcher: `Write|Edit`

```sh
input=$(cat); f=${input#*\"file_path\":\"}; [ "$f" = "$input" ] && f=${input#*\"file_path\": \"}; [ "$f" = "$input" ] && exit 0; file=${f%%\"*}; base=$(basename "$file"); case "$base" in .env|.env.*) echo "BLOCKED: 機密ファイル $base の編集は禁止されています。" >&2; exit 2;; esac; case "$file" in *credential*|*secret*|*.pem|*.key) echo "BLOCKED: 機密ファイル $base の編集は禁止されています。" >&2; exit 2;; esac; exit 0
```

## PreToolUse: Linter/Formatter/型チェッカー設定変更ブロック

matcher: `Write|Edit`

保護対象ファイルリストは `/harness-init` が手順3の検出結果から動的生成する。テンプレ:

```sh
input=$(cat); f=${input#*\"file_path\":\"}; [ "$f" = "$input" ] && f=${input#*\"file_path\": \"}; [ "$f" = "$input" ] && exit 0; file=${f%%\"*}; base=$(basename "$file"); case "$base" in <DETECTED_CONFIG_FILES>) echo "BLOCKED: Linter/Formatter/型チェッカー設定 $base の変更は禁止されています。変更が必要な場合はユーザーに相談してください。" >&2; exit 2;; esac; exit 0
```

`<DETECTED_CONFIG_FILES>` には検出したファイル（`ruff.toml|dprint.json|.prettierrc*|.eslintrc*|eslint.config.*|biome.json|rustfmt.toml|mypy.ini|pyrightconfig.json` 等）をパイプ区切りで展開する。型チェッカー設定も必ず含める。

## UserPromptSubmit: フィードバック捕捉リマインダ（言語非依存・常に含める）

matcher: なし（UserPromptSubmit イベント）

ユーザー発話に修正語が含まれたら、応答前に「フィードバックを Engram に保存せよ」という
リマインダを stdout でコンテキストに注入する。**ブロックしない・常に `exit 0`（fail-open）**。
自己進化ループの起点（`[feedback]` 保存）がモデルの気づき任せで漏れるのを防ぐ。

```sh
input=$(cat); p=${input#*\"prompt\":\"}; [ "$p" = "$input" ] && p=${input#*\"prompt\": \"}; [ "$p" = "$input" ] && exit 0; p=${p%%\"*}; case "$p" in *違う*|*ちがう*|*そうじゃな*|*じゃなくて*|*こうして*|*直して*|*やめて*|*戻して*|*revert*) echo "FEEDBACK検知: memory.md に従い、この指摘を [feedback] として Engram に mem_save してから応答してください（未保存だと自己進化ループが発火しません）。";; esac; exit 0
```

- `prompt` 抽出は file_path と同じくスペース有無の両変異にフォールバックする
- UserPromptSubmit の stdout はコンテキストに追加される（ブロック用途ではない）
- 修正語は誤検知の少ないものに絞る（`なんで` 等の汎用疑問語は入れない）

## SessionStart: 健全性プローブ（言語非依存・常に含める）

matcher: `startup`（AUTO-EVOLVE と同じ startup の hooks 配列に併記する）

engram 不在・`settings.local.json` 破損など、致命でないが要注意な劣化を1行警告する。
**常に `exit 0`**。settings.json 自体の破損は hooks 自体が無効化されるため検査対象外
（代わりに `bash .claude/scripts/doctor.sh` で明示検査する）。

```sh
w=""; command -v engram >/dev/null 2>&1 || w="engram未検出 "; f="${CLAUDE_PROJECT_DIR:-$PWD}/.claude/settings.local.json"; [ -f "$f" ] && ! python3 -m json.tool "$f" >/dev/null 2>&1 && w="${w}settings.local.json不正 "; [ -n "$w" ] && echo "HARNESS警告: ${w}— bash .claude/scripts/doctor.sh で確認を推奨"; exit 0
```

## Stop: 条件付きCI再実行

matcher: なし（Stop イベント）

```sh
changed=$(git diff --name-only HEAD 2>/dev/null | grep -E '\.(py|ts|js|rs|go)$' | head -1); if [ -n "$changed" ]; then result=$(<CI_CHECK_CMD> 2>&1 | tail -20); echo "$result"; fi; exit 0
```

- 拡張子は検出した言語に応じて `/harness-init` が生成
- `<CI_CHECK_CMD>` は `task-runners/` モジュールから導出した代表CIコマンド
