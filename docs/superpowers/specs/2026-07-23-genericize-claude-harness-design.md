# `.claude` ハーネス汎用化 設計

## 目的

`self-evolve-harness` リポジトリの `.claude/` は、配布用テンプレートでありながら
中身が元プロジェクト `jum-blog`（`ng_core` クリーンアーキ / Next.js / uv）に
instantiate された状態のまま残っている。これを **`/harness-init` 実行前のシード状態**へ戻し、
任意のプロジェクトに `.claude/` を投入して `/harness-init` を回せば再インスタンス化できる
汎用テンプレートにする。

## 方針

`/harness-init` は「スケルトンの空セクションを検出結果で埋める」差分更新設計。
よって汎用化 = プロジェクト固有の記入済み内容をプレースホルダに戻し、
`/harness-init` が生成する成果物（言語フック等）をテンプレから除去する。

## 変更対象

### rules/（骨格維持・固有中身をプレースホルダ化）

| ファイル | 変更 |
|---|---|
| `domain.md` | init 手順8d のスケルトンに全置換（全セクションをプレースホルダコメント化） |
| `architecture.md` | `paths` を `src/**` に。層構造/依存方向/配置/禁止パターンをスケルトン化 |
| `coding.md` | 汎用骨格は維持。「言語固有規約」節の Python/TS 実体をプレースホルダに。`paths` を `src/**`, `scripts/**` |
| `testing.md` | `paths` を汎用グロブに。言語固有節をプレースホルダに |
| `workflow.md` / `debugging.md` / `memory.md` | 変更なし（汎用済み） |

### settings.json（言語非依存の安全フックのみ）

- 残す: SessionStart(AUTO-EVOLVE) / PreToolUse Bash(破壊コマンド) / PreToolUse Write|Edit(機密 + 汎用フォーマッタ設定保護)
- 削除: PostToolUse の `uv run ruff` フォーマッタ、`ng_core` アーキ守衛（`/harness-init` が検出結果から生成）
- 理由: JSON はコメント不可。未展開プレースホルダを残すとリテラル実行で壊れるため完全除去

### settings.local.json

- `allow` を最小シード（`git` / `gh` / `command -v` / `engram` / `codegraph` / `claude mcp`）に。
  `uv`/`make`/`npm`/`npx`/`node` は削除（`/harness-init` が検出時に提案）

### _reference.md

- 「ファイル構成」節の jum-blog 固有コメント（`ng_core` 等）を汎用表現に

### 削除

- `settings.json.bak`, `scheduled_tasks.lock`

## スコープ外（NOTICED BUT NOT TOUCHING）

- `_reference.md` / `workflow.md` が参照する `/loop-protocol` スキルの実体が `.claude/skills/` に無い
- リポジトリが git 未初期化（このためスペックのコミットは行わない）

## 検証

- 変更後、`grep -rnE '\b(ng_core|ng_cli|jum-blog|apps/backend|apps/frontend|uv run|RawItem|Gemini)\b' .claude/`
  で残存する固有語がゼロ（`domain.md` の例示を除く）であることを確認
- `python3 -m json.tool` で settings.json / settings.local.json が妥当な JSON であることを確認
