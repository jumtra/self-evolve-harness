# 記憶バックエンド: engram（Engram MCP サーバー）

> `common.md` に続けて `.claude/rules/memory.md` に合成される。
> 記憶の保存・検索・想起・件数カウントを Engram MCP の操作で定義する。

## 記憶層（Engram MCP）

記憶層は Engram MCP サーバーを使う。記憶はエージェントが能動的に Engram へ書き、
検索で引く。リポジトリ内に記憶ファイルは置かない。

Engram のツールは `mcp__engram__` プレフィックスで提供される。正確なツール名・引数は
セッション開始時のツール一覧で確認してから使う（以下の「保存」「検索」の呼び方は
機能名であり、実際のツール名に読み替えること）。

> 複数ツール（Codex / OpenCode 等）で同じ記憶を共有するには、各ツールにも
> Engram MCP を登録する（`/harness-sync` が案内する）。同じ Engram インスタンスを
> 指す限り、どのツールから書いた記憶も共有される。

## 記憶の保存

1 つの記憶 = Engram の 1 記憶単位。

- 識別子 `<type>_<slug>` を name 相当として保存する
- 本文は共通節の形式（事実。feedback と project は **Why:** / **How to apply:** 付き）
- メタデータ（`type` / `evolve: pending|done` / `count` / `evolved_to`）は Engram の
  メタデータ・タグ機能で保持する。タグ機能が無い場合は本文の先頭に
  YAML frontmatter と同じ形式で書き、grep/検索で取れる形にする
- 索引は Engram 内の `MEMORY.md` という name の記憶 1 本に集約する
  （インデックス用の専用記憶。共通節の索引ルールはこれに適用）

## セッション開始時の想起

セッション開始時に Engram から索引記憶（`MEMORY.md`）を取得し、
関係しそうな記憶を検索で引く（共通節の「想起（義務）」に従う）。
フックから MCP は叩けないため、想起はエージェント自身が行う。

## 過去のコンテキスト検索

Engram の検索クエリで探す。シェルの `grep` は使わない（記憶はリポジトリに無い）。

## 未処理フィードバックの数え方

Engram の検索で `evolve: pending`（メタデータまたは本文の frontmatter 行）を持つ
記憶の件数を数える。これが3以上で AUTO-EVOLVE 対象。

> file バックエンドと違い SessionStart フック（シェル）から件数を決定論的に
> 数えられないため、`settings.json` の SessionStart フックは「Engram で
> `evolve: pending` を検索して3件以上なら evolver を起動せよ」という指示文を
> 注入する形になる。`doctor.sh` の索引サイズ検査も file バックエンド専用のため
> 対象外（代わりに索引記憶の行数上限 200 行を想起時に意識する）。
