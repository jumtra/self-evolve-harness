# 言語非依存フック雛形

`/harness-init` が常に含める言語非依存の安全装置フック。検出した言語・タスクランナーのフックは `languages/` `task-runners/` から合成して追加する。

## フック入力の受け取り方（共通規約）

Claude Code はフックにツール入力を**環境変数では渡さない**。入力は stdin の JSON
（`tool_input.file_path` / `tool_input.command` 等）で渡される。外部ツール（jq 等）に依存せず、
抽出は POSIX シェルの組み込み（パラメータ展開・case）のみで行う:

```sh
# file_path 抽出の共通イディオム（jq 不使用・組み込みのみ。コンパクト/スペース入り JSON 両対応）
input=$(cat); f=${input#*\"file_path\":\"}; [ "$f" = "$input" ] && f=${input#*\"file_path\": \"}; [ "$f" = "$input" ] && exit 0; file=${f%%\"*}
```

- ブロック時のメッセージは **stderr**（`>&2`）に出して `exit 2`（exit 2 で Claude に渡るのは stderr）
- ブロックは **PreToolUse のみ**で行う。PostToolUse はツール実行後のため exit 2 でもブロックできない
- Bash コマンドの判定は file_path 抽出をせず、stdin 全体への `case` サブストリングマッチで行う
- **`$VAR` の直後に日本語などのマルチバイト文字を置かない**。macOS 同梱の bash 3.2 は変数名解析で
  直後のマルチバイト文字の先頭バイトを変数名に取り込み、出力が壊れる（例: `"（$idx。"` →
  `$idx\xe3` が空変数 `idx\xe3` と解釈される）。変数は必ず `"${VAR}。"` と波括弧で囲む

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

ユーザー発話に修正語が含まれたら、応答前に「フィードバックをファイルメモリ（feedback メモリ・`evolve: pending`）に保存せよ」という
リマインダを stdout でコンテキストに注入する。**ブロックしない・常に `exit 0`（fail-open）**。
feedback メモリの保存（自己進化ループの起点）がモデルの気づき任せで漏れるのを防ぐ。

```sh
input=$(cat); p=${input#*\"prompt\":\"}; [ "$p" = "$input" ] && p=${input#*\"prompt\": \"}; [ "$p" = "$input" ] && exit 0; p=${p%%\"*}; case "$p" in *違う*|*ちがう*|*そうじゃな*|*じゃなくて*|*こうして*|*直して*|*やめて*|*戻して*|*revert*) echo "FEEDBACK検知: .claude/rules/memory.md に従い、この指摘を feedback メモリ（metadata に evolve: pending）として保存してから応答してください（未保存だと自己進化ループが発火しません）。";; esac; exit 0
```

- `prompt` 抽出は file_path と同じくスペース有無の両変異にフォールバックする
- UserPromptSubmit の stdout はコンテキストに追加される（ブロック用途ではない）
- 修正語は誤検知の少ないものに絞る（`なんで` 等の汎用疑問語は入れない）

## SessionStart: 健全性プローブ（言語非依存・常に含める）

matcher: `startup`（AUTO-EVOLVE・索引注入と同じ startup の hooks 配列に併記する）

メモリ索引の欠如・codegraph 未検出・`settings.local.json` 破損など、致命でないが要注意な劣化を1行警告する。
**常に `exit 0`**。settings.json 自体の破損は hooks 自体が無効化されるため検査対象外
（代わりに `bash .claude/scripts/doctor.sh` で明示検査する）。

```sh
root=$(dirname "$(git -C "${CLAUDE_PROJECT_DIR:-$PWD}" rev-parse --path-format=absolute --git-common-dir 2>/dev/null)"); mem="$root/.agent-memory"; w=""; [ -f "$mem/MEMORY.md" ] || w="メモリの索引なし（$mem/MEMORY.md） "; command -v codegraph >/dev/null 2>&1 || w="${w}codegraph未検出 "; f="${CLAUDE_PROJECT_DIR:-$PWD}/.claude/settings.local.json"; [ -f "$f" ] && ! python3 -m json.tool "$f" >/dev/null 2>&1 && w="${w}settings.local.json不正 "; [ -n "$w" ] && echo "HARNESS警告: ${w}— bash .claude/scripts/doctor.sh で確認を推奨"; exit 0
```

engram バックエンドでは記憶はリポジトリに置かないため、この雛形の
メモリ索引チェック行を除いて生成する（`[ -f "$mem/MEMORY.md" ] || w=...` の部分）。

## SessionStart: メモリ索引注入（file バックエンドのみ）

matcher: `startup`

リポジトリローカル `.agent-memory/` は Claude Code 組み込み自動メモリと違い自動ロード
されないため、SessionStart で索引（上限の200行まで）をコンテキストに注入する。
**常に `exit 0`**。engram バックエンドでは生成しない（索引取得は Engram 経由でエージェントが行う）。

```sh
root=$(dirname "$(git -C "${CLAUDE_PROJECT_DIR:-$PWD}" rev-parse --path-format=absolute --git-common-dir 2>/dev/null)"); idx="$root/.agent-memory/MEMORY.md"; if [ -f "$idx" ]; then echo "メモリ索引（${idx}。詳細は Read、規約は .claude/rules/memory.md）:"; head -n 200 "$idx"; fi; exit 0
```

## SessionStart: AUTO-ORGANIZE 通知（file バックエンドのみ）

matcher: `startup`

索引が閾値（20KB）を超えたら、段1の整理を自動実行させる指示を注入する。**常に `exit 0`**。
engram バックエンドでは索引がシェルから測れないため生成しない
（engram 時の整理は想起時に索引記憶の行数を見て行う）。

```sh
root=$(dirname "$(git -C "${CLAUDE_PROJECT_DIR:-$PWD}" rev-parse --path-format=absolute --git-common-dir 2>/dev/null)"); idx="$root/.agent-memory/MEMORY.md"; if [ -f "$idx" ]; then b=$(wc -c <"$idx"); if [ "$b" -gt 20000 ]; then echo "AUTO-ORGANIZE: メモリ索引が ${b}B（閾値20KB）。.claude/rules/memory.md の段1手順（完了済みprojectメモリ削除・索引行の150字圧縮）を確認せずその場で実行し、結果を1行で報告してから作業に着手してください。"; fi; fi; exit 0
```

## SessionStart: AUTO-EVOLVE 通知（バックエンド別）

matcher: `startup`

未処理フィードバック（`evolve: pending`）が3件以上なら通知を注入する。**常に `exit 0`**。

### file バックエンド（grep で決定論的にカウント）

```sh
root=$(dirname "$(git -C "${CLAUDE_PROJECT_DIR:-$PWD}" rev-parse --path-format=absolute --git-common-dir 2>/dev/null)"); mem="$root/.agent-memory"; n=$(grep -l "^ *evolve: pending" "$mem"/*.md 2>/dev/null | wc -l); if [ "$n" -ge 3 ]; then echo "AUTO-EVOLVE: 未処理フィードバックが ${n} 件蓄積されています（$mem の evolve: pending）。Agent ツールで evolver エージェントをバックグラウンド起動してから、ユーザーの依頼に着手してください（並行処理。ユーザーを待たせない）。"; fi; exit 0
```

### engram バックエンド（シェルから MCP は叩けないため指示注入）

```sh
echo "AUTO-EVOLVE確認: 記憶バックエンドは Engram（.claude/rules/memory.md 参照）。Engram で evolve: pending の記憶を検索し、3件以上なら Agent ツールで evolver エージェントをバックグラウンド起動してから、ユーザーの依頼に着手してください（並行処理。ユーザーを待たせない）。"; exit 0
```

## Stop: 条件付きCI再実行

matcher: なし（Stop イベント）

```sh
changed=$(git diff --name-only HEAD 2>/dev/null | grep -E '\.(py|ts|js|rs|go)$' | head -1); if [ -n "$changed" ]; then result=$(<CI_CHECK_CMD> 2>&1 | tail -20); echo "$result"; fi; exit 0
```

- 拡張子は検出した言語に応じて `/harness-init` が生成
- `<CI_CHECK_CMD>` は `task-runners/` モジュールから導出した代表CIコマンド
