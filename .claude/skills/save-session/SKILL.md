---
name: save-session
description: >
  セッション保存スキル。作業コンテキストを整理してユーザーに報告し、
  進行中の作業・決定待ちの論点・確認予定を記憶層（バックエンドは memory.md 選択式）の project メモリに追記・更新する。
  /create-pr 完了後、/loop 完了後、セッション終了時に自動で呼ばれる。
---

# セッション保存

セッションの作業コンテキストを整理し、ユーザーに報告する。
整理した内容のうち次のセッションに要るものを、記憶層の該当する project メモリに書く。

> SessionEnd の自動記録 hook はない。能動的に記憶へ書く。
> セッションごとの日誌は作らない。記憶の規約（1 話題 1 単位等）は `memory.md`。

## トリガー

`memory.md` の「セッション保存」節で規定: `/create-pr` 実行後 / `/loop` のループ完了後 /
ユーザーがセッション終了を示唆したとき。

## 手順

### 1. 差分サマリ生成

git の状態から作業内容を自動取得する:

- 現在のブランチ: !`git branch --show-current`
- main からのコミット: !`git log main..HEAD --oneline 2>/dev/null | head -10`
- 変更ファイル: !`git diff main...HEAD --name-only 2>/dev/null | head -20`

### 2. コンテキスト整理

以下を各 2-3 行以内でまとめる:

- **やったこと**: git log から自動抽出 + 補足
- **次のアクション**: 残タスクや次回最初にやるべきこと
- **判断ログ**: セッション中の重要な設計判断（あれば）
- **未解決事項**: ブロッカーや保留事項（あれば）

### 3. ユーザーへの報告

整理した内容を以下の形式で提示する:

```text
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

### 4. メモリへの記録

報告した内容のうち、**リポジトリに書けない今の状況**だけをメモリに残す
（進行中の作業・決定待ちの論点・いつ何を確かめるか → 該当する `project_<slug>` メモリ。
セッション中に受けた指摘 → `feedback_<slug>`（`evolve: pending`。`memory.md` のフィードバック検知どおり））。

**file バックエンド**（既定。`.claude/rules/memory.md` のバックエンド節が file の場合）:

1. メモリディレクトリを求める:
   ```bash
   ROOT=$(dirname "$(git rev-parse --path-format=absolute --git-common-dir)")
   MEMDIR="$ROOT/.agent-memory"
   ```
2. `MEMORY.md` の索引と `grep -ril "<話題の語>" "$MEMDIR"` で、同じ話題の project メモリを探す
3. あれば Read してから追記・更新する（古くなった記述は直す。重複を作らない）。
   無ければ `project_<slug>.md` を新規作成し（frontmatter は `memory.md` の形式、
   **Why:** と **How to apply:** を付ける）、`MEMORY.md` に索引行を 1 行足す
4. 日付は「今日」「明日」ではなく絶対日付（YYYY-MM-DD 等）で書く
5. 手順・決まり・再利用できるやり方はメモリに書かず、`CLAUDE.md` / `AGENTS.md` /
   `.claude/skills/` 側に書く（`memory.md` 規約。変更はユーザーに報告する）

**engram バックエンド**: 上記の読み書きを Engram の保存・検索ツールで行う
（`.claude/rules/memory.md` が出荷状態（file）の場合の操作定義は
`.claude/skills/harness-init/memory-backends/engram.md` を参照）。
