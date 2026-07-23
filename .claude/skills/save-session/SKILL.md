---
name: save-session
description: >
  セッション保存スキル。作業コンテキストを整理してユーザーに報告し、
  Engram の mem_save で記憶層に記録する。
  /create-pr 完了後、/loop 完了後、セッション終了時に自動で呼ばれる。
---

# セッション保存

セッションの作業コンテキストを整理し、ユーザーに報告する。
整理したサマリを Engram（記憶層）に `mem_save` で記録する。

> claude-mem のような SessionEnd 自動記録はない。能動的に Engram に保存する。

## トリガー

以下のタイミングで呼ばれる（memory.md ルールで規定）:

- `/create-pr` 実行後
- `/loop` `/goal` のループ完了後
- ユーザーがセッション終了を示唆したとき

## 手順

### 1. 差分サマリ生成

git の状態から作業内容を自動取得する:

- 現在のブランチ: !`git branch --show-current`
- main からのコミット: !`git log main..HEAD --oneline 2>/dev/null | head -10`
- 変更ファイル: !`git diff main...HEAD --name-only 2>/dev/null | head -20`

### 2. コンテキスト整理

以下を簡潔にまとめる（各項目2-3行以内）:

- **やったこと**: git log から自動抽出 + 補足
- **次のアクション**: 残タスクや次回最初にやるべきこと
- **判断ログ**: セッション中の重要な設計判断（あれば）
- **未解決事項**: ブロッカーや保留事項（あれば）

### 3. ユーザーへの報告

整理した内容をユーザーに提示する。以下の形式で出力する:

```
## セッションサマリ

**ブランチ**: <ブランチ名>

### やったこと
<要約>

### 次のアクション
- [ ] <次にやること>

### 判断ログ（あれば）
- <判断>: <理由>

### 未解決事項（あれば）
- <ブロッカー>
```

### 4. Engram への記録

報告したセッションサマリを Engram に記録する。MCP ツールがロード済みなら
`mem_save` を、未ロードなら CLI を使う:

- MCP: `mem_save` に title（ブランチ名＋日付等）と、整理したサマリ本文を渡す
- CLI: `engram save "<title>" "<サマリ>" --project <プロジェクト名>`

プロジェクト名はリポジトリ名（`basename "$(git rev-parse --show-toplevel)"`。
MCP 利用時は `mem_current_project` の `project` 値と一致する）を指定する。
記録後は `mem_search` / `engram search` で過去セッションを検索できる。
