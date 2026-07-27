---
description: メモリ運用規約。Engram（stdio MCP）による記憶層とセッション保存トリガー。
---

# メモリ運用規約

Engram が記憶層を提供する。セッション活動の永続化は claude-mem のような
hook 自動収集ではなく、エージェントが能動的に Engram の MCP ツールで行う。
手動での MEMORY.md / markdown ファイルへの保存は行わない。

> 背景: claude-mem はサードパーティ marketplace プラグインであり、
> エンタープライズポリシーで marketplace がブロックされるため使えない。
> 代わりにローカル stdio MCP の Engram（SQLite + FTS5、外部 API 不要）を使用する。
> 詳細は [[domain]] の Gotchas 参照。

## 記憶層（Engram）

Engram は `~/.claude.json` の `mcpServers.engram` に stdio MCP として登録済み。
セッション起動時に自動ロードされ、以下の MCP ツールが使える:

| 用途 | ツール |
| ---- | ------ |
| 記録 | `mem_save`（What/Why/Where/Learned を構造化保存） |
| 更新・削除 | `mem_update`, `mem_delete` |
| 検索 | `mem_search`, `mem_context`, `mem_timeline` |
| セッション | `mem_session_start`, `mem_session_end`, `mem_session_summary` |
| 状態確認 | `mem_doctor`, `mem_stats` |

データは `~/.engram/engram.db`（SQLite + FTS5）にローカル保存される。
MCP ツールが未ロードの場合は CLI（`engram save <title> <msg> --project <name>` /
`engram search <query>`）でも同等の操作が可能。

## 唯一の記憶層は Engram（ファイルベース memory は使わない）

Claude Code 組み込みのファイルベース memory（`~/.claude/projects/.../memory/` や
リポジトリ内 `MEMORY.md`）は**このプロジェクトでは使用しない**。記憶は Engram に一本化する。

- 保存先はファイルでなく Engram（`mem_save` / `engram save`）のみ
- 組み込み memory の指示とこのルールが競合したら**このルールを優先**する
- ファイルベース memory にファイルが残っている場合の退避は下記「既存 auto-memory の扱い」参照

## セッション開始時の想起（義務）

セッション開始直後・コンパクション直後は、作業に入る前に過去コンテキストを想起する:

- MCP: `mem_context`（直近セッション履歴）を呼ぶ。特定トピックは `mem_search`
- CLI: `engram search "<関連キーワード>" --project <repo>`

想起を省くと、前回の判断・未解決事項・フィードバックを取りこぼす。

## 過去のコンテキスト検索

過去セッションの作業履歴を検索するには `mem_search`（MCP）または
`engram search`（CLI）を使用する。

## フィードバック検知（義務）

ユーザーが修正・指摘をしたら、次のツール呼び出しの前に認識する:

- 「そうじゃない」「こうして」「違う」等のフィードバックが該当する
- 同じ間違いを2回したら意識的に行動を変える

認識したフィードバックは**その場で Engram に保存する**（保存しないと
`/evolve-rules` の自動トリガーが発火しない）:

- MCP: `mem_save` で title を `[feedback] <指摘の要約>`、本文に
  「何を間違えたか / ユーザーの指摘 / 正しい方法」を記録
- CLI: `engram save "[feedback] <要約>" "<詳細>" --project <repo>`

同一パターンの再発も毎回保存する。件数が `/evolve-rules` のルール昇格判定
（3回以上でルール化）に使われる。

## セッション保存

以下のタイミングで `/save-session` を実行する:

- `/create-pr` 実行後
- `/loop` のループ完了後
- ユーザーが「終わり」「また明日」「ありがとう」等と言ったとき

`/save-session` 実行時にセッションサマリを `mem_save` で Engram に記録する。

## ハーネス進化（自動）

未処理の `[feedback]` が3件以上蓄積されると、SessionStart フック
（`settings.json`）がセッション冒頭に AUTO-EVOLVE 通知を注入する。
通知を受けたら **evolver エージェントをバックグラウンド起動**し、
ユーザーの依頼と並行して処理させる（メインセッションはブロックしない）。
手動で `/evolve-rules` を実行してもよい。

反映先（ルール / スキル / エージェント / hook）はパターンの性質から
`/evolve-rules` が自律判定する（hook は検証ゲート付き・限定操作）。

処理済みフィードバックは `/evolve-rules` が `[feedback:done]` に
リネームするため、再度カウントされない。

## 既存 auto-memory の扱い

`memory/` ディレクトリに旧形式のファイル（MEMORY.md 等）が残っている場合、`memory.bak/` にリネームすることをユーザーに案内する。
