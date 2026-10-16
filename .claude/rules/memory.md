---
description: メモリ運用規約。Claude Code 組み込みのファイルベース自動メモリ（memory/）による記憶層とセッション保存トリガー。
---

# メモリ運用規約

記憶層は Claude Code 組み込みのファイルベース自動メモリ（`memory/` ディレクトリ）を使う。
外部の記憶用 MCP サーバーや hook 自動収集は使わない（導入しない決定）。
記憶はエージェントが能動的に Markdown ファイルとして書き、索引 `MEMORY.md` で引く。

> 背景: claude-mem はサードパーティ marketplace プラグインであり、
> エンタープライズポリシーで marketplace がブロックされるため使えない。
> 別の記憶用 MCP も入れず、追加導入の要らない組み込みのファイルメモリに一本化する。

## 記憶層（ファイルメモリ）

### 置き場所

`~/.claude/projects/<リポジトリの根の絶対パスの / を - にしたもの>/memory/`

リポジトリの根は worktree の中でも本体を指すよう、git-common-dir から求める:

```bash
ROOT=$(dirname "$(git rev-parse --path-format=absolute --git-common-dir)")
MEMDIR="$HOME/.claude/projects/$(echo "$ROOT" | sed 's#/#-#g')/memory"
```

例: 根が `~/work/app` なら `~/.claude/projects/-home-user-work-app/memory/`

### 1 つの記憶 = 1 ファイル

| 項目       | 決まり                                                                                                                           |
| ---------- | -------------------------------------------------------------------------------------------------------------------------------- |
| ファイル名 | `<type>_<slug>.md`（例: `feedback_reply_in_japanese.md`, `project_home_layout.md`）                                              |
| 本文       | 事実を書く。feedback と project は **Why:** と **How to apply:** の行を付ける                                                    |
| 関連       | 他の記憶へは `[[name]]` でリンク                                                                                                 |
| 索引       | `MEMORY.md` に `- [題](ファイル名.md) — 一言` を 1 行ずつ。中身は索引に書かない。1 行 150 字まで（索引は毎セッション全文が載る） |
| 重複       | 新規作成の前に検索し、同じ話題があれば既存ファイルを更新する                                                                     |

frontmatter:

```markdown
---
name: <kebab-case の slug>
description: <1 行の要約>
metadata:
  type: user | feedback | project | reference
---
```

| type        | 何を残すか                                             |
| ----------- | ------------------------------------------------------ |
| `user`      | ユーザー本人の属性・好み                               |
| `feedback`  | ユーザーの指摘・修正（自己進化の入力。下記）           |
| `project`   | 進行中の作業・決定・決定待ちの論点・いつ何を確かめるか |
| `reference` | 外部サービスの鍵の場所・API の読み方など参照情報       |

メモリには「リポジトリに書けない今の状況」だけを残す。手順や決まりはメモリではなく
CLAUDE.md / AGENTS.md / `.claude/rules/` / `.claude/skills/` に書く。

## セッション開始時の想起（義務）

`MEMORY.md` はセッション開始時に自動で読み込まれる。作業に入る前に、索引から
関係しそうな記憶ファイルを Read して前回の判断・未解決事項・フィードバックを確認する。
コンパクション直後も同様に読み直す。

想起を省くと、前回の判断・未解決事項・フィードバックを取りこぼす。

## 過去のコンテキスト検索

MCP は無い。`grep` で探す:

```bash
grep -ril "<語>" "$MEMDIR"
```

見つかったファイルを Read する。

## フィードバック検知（義務）

ユーザーが修正・指摘をしたら、次のツール呼び出しの前に認識する:

- 「そうじゃない」「こうして」「違う」等のフィードバックが該当する
- 同じ間違いを2回したら意識的に行動を変える

認識したフィードバックは**その場でメモリに保存する**（保存しないと
`/evolve-rules` の自動トリガーが発火しない）:

- `feedback_<slug>.md`（`type: feedback`）を作り、metadata に `evolve: pending` を付ける
- 本文に「何を間違えたか / ユーザーの指摘 / 正しい方法」を書き、**Why:** と **How to apply:** を付ける
- `MEMORY.md` に索引行を 1 行足す

```markdown
---
name: reply-in-japanese
description: 説明はいつも日本語で返す
metadata:
  type: feedback
  evolve: pending
  count: 1
---

英語で返して「日本語」と指摘された（2026-10-14）。

**Why:** ユーザーは日本語で読みたい。
**How to apply:** 報告・説明・質問はすべて日本語で書く。
```

同一パターンの再発は**新しいファイルを作らず同じファイルに日付つきで追記**し、
metadata の `count: N` を増やす（処理済みでも再発したら `evolve: pending` に戻す）。
`count` が `/evolve-rules` のルール昇格判定（3回以上でルール化）に使われる。

## セッション保存

以下のタイミングで `/save-session` を実行する:

- `/create-pr` 実行後
- `/loop` のループ完了後
- ユーザーが「終わり」「また明日」「ありがとう」等と言ったとき

`/save-session` はセッションごとの日誌ファイルを作らない。進行中の作業・決定待ちの論点・
いつ何を確かめるかを、該当する project メモリに追記・更新する（日付は絶対日付）。

## メモリが増えたときの移行

索引 `MEMORY.md` は毎セッション全文が載る。`bash .claude/scripts/doctor.sh` が 20KB で警告する（上限は 25KB か 200 行のどちらか先）。警告が出たら、次の順で手を打つ。上の段で足りるうちは下の段へ進まない。

| 段 | 条件 | やること |
| -- | ---- | -------- |
| 1 | 索引が 20KB 超 | 索引の行を 1 行 150 字までに縮める。完了した project メモリはファイルごと消して索引の行も消す。リポジトリに移した決まりのメモリも同じ |
| 2 | それでも 20KB 超（記憶が 100 件前後） | 話題ごとに索引を分ける：`MEMORY.md` には話題ごとの見出しと 1 行の説明だけ、細かい行は `memory/index_<話題>.md` に置く。想起は話題の索引を開いてから個別のメモリを Read する |
| 3 | 記憶が数百件・索引を分けても探すのに手間取る | 検索型の記憶（SQLite + FTS5 の stdio MCP など）へ移す。常時載るのは索引でなくツール定義だけになり、必要な分だけ検索で引ける |

段 3 に移すときの手順:

1. `memory/*.md` を全部読み、type・名前・本文・metadata（`evolve`・`count`）を保ったまま検索型へ 1 件ずつ登録する（移行前に `memory/` を tgz で控える）
2. `.claude/rules/memory.md` の記憶層・想起・検索・フィードバック保存の節を、移行先の保存・検索の操作に書き換える。`evolve: pending` の数え方は、移行先で同じ数が取れる式に直す
3. SessionStart のフック（未処理フィードバックの数え方・健全性の確かめ）と `doctor.sh` の記憶の検査、`save-session`・`evolve-rules`・`evolver` の記憶への読み書きを、移行先の操作に合わせる
4. 常時のコストが増える（ツール定義・保存や検索ごとの呼び出し）。段 2 までで足りているうちは移さない
5. 移行後はファイルの `memory/` を残さない（二重の正本を作らない）。索引を消して `doctor.sh` が通ることを確かめる

## ハーネス進化（自動）

未処理フィードバック（`evolve: pending` のメモリファイル）が3件以上たまると、SessionStart フック
（`settings.json`）がセッション冒頭に AUTO-EVOLVE 通知を注入する。未処理の数え方はフックと同じ式:

```bash
grep -l '^ *evolve: pending' "$MEMDIR"/*.md 2>/dev/null | wc -l
```

通知を受けたら **evolver エージェントをバックグラウンド起動**し、
ユーザーの依頼と並行して処理させる（メインセッションはブロックしない）。
手動で `/evolve-rules` を実行してもよい。

反映先（ルール / スキル / エージェント / hook / CLAUDE.md・AGENTS.md）はパターンの性質から
`/evolve-rules` が自律判定する（hook は検証ゲート付き・限定操作）。

反映したフィードバックは `/evolve-rules` が metadata を `evolve: done` と
`evolved_to: <反映先のパス>` に書き換えるため、再度カウントされない。中身が完全に
リポジトリ側に移ったなら、ファイルを消して `MEMORY.md` の行も消してよい。
