# 記憶バックエンド: file（リポジトリローカル）

> `common.md` に続けて `.claude/rules/memory.md` に合成される。
> 記憶の置き場所と、その保存・検索・想起・件数カウントの具体的な操作を定義する。

## 記憶層（リポジトリローカルのファイルメモリ）

記憶層はリポジトリ内の `.agent-memory/` ディレクトリ（Markdown ファイル）を使う。
外部の記憶用 MCP サーバーや hook による自動収集は使わない（導入しない決定）。
記憶はエージェントが能動的に Markdown ファイルとして書き、索引 `MEMORY.md` で引く。

> 背景: claude-mem 等のサードパーティ marketplace プラグインは
> エンタープライズポリシーでブロックされるため使えない。
> また、Claude Code 組み込みの自動メモリ（`~/.claude/projects/.../memory/`）は
> ホームディレクトリ配下で Codex / OpenCode など他ツールと共有できないため、
> リポジトリローカルの `.agent-memory/` に一本化する（`/harness-sync` が
> 各ツールにこの場所を読むよう案内する）。`.agent-memory/` はリポジトリにコミットする。

### 置き場所

リポジトリの根（worktree の中でも本体を指す）直下の `.agent-memory/`:

```bash
ROOT=$(dirname "$(git rev-parse --path-format=absolute --git-common-dir)")
MEMDIR="$ROOT/.agent-memory"
```

1 つの記憶 = 1 ファイル。ファイル名は `<type>_<slug>.md`
（例: `feedback_reply_in_japanese.md`）。索引は `$MEMDIR/MEMORY.md`。

## セッション開始時の想起

SessionStart フック（`settings.json`）が索引 `MEMORY.md`（上限の200行まで）をコンテキストに注入する。
作業に入る前に、索引から関係しそうな記憶ファイルを Read する。

## 過去のコンテキスト検索

`grep` で探す:

```bash
grep -ril "<語>" "$MEMDIR"
```

見つかったファイルを Read する。

## 未処理フィードバックの数え方（フックと同じ式）

```bash
grep -l '^ *evolve: pending' "$MEMDIR"/*.md 2>/dev/null | wc -l
```

これが3以上で AUTO-EVOLVE 通知が発火する（共通節の「ハーネス進化」参照）。
