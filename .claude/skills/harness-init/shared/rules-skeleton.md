# 汎用骨格（言語非依存）

`/harness-init` が rules 生成のベースとする言語非依存の原則。`languages/` モジュールの `coding-rules` / `testing-rules` セクションを「言語固有規約」セクションにマージする。

## coding.md 骨格

以下のセクションを言語非依存として固定し、末尾の「言語固有規約」セクションに `languages/*.md` の `coding-rules` を埋め込む:

- 設計原則（YAGNI / KISS / DRY）
- TDD（Red → Green → Refactor）
- コメント（WHY を示す）
- 関数設計（単一責任・複雑度≤5・早期リターン）
- データ構造（イミュータブル優先）
- エラーハンドリング（Fail Fast）
- 冪等性とロバスト性
- Linter / Formatter 規律
- スコープ規律（NOTICED BUT NOT TOUCHING）
- 合理化に注意

> テンプレ時点の `.claude/rules/coding.md` がこの骨格の実体。`/harness-init` は「言語固有規約」セクションのみ埋める（差分更新）。

## testing.md 骨格

以下を言語非依存として固定し、「言語固有規約」セクションに `languages/*.md` の `testing-rules` を埋め込む:

- DAMP 原則（判定基準: テスト1つを切り出して入力値・操作・期待値が見えるか）
- ヘルパー禁止（例外は外部リソースのライフサイクル管理のみ）
- 命名（対象・状況・期待結果）と Good/Bad 例
- 構造（AAA パターン・1テスト1アサーション）
- セットアップ / fixture（最小限。ヘルパー禁止と同じ境界）
- パラメトライズ
- カバレッジ（80%以上）
- 合理化テーブル（テスト編）

言語固有規約を埋めるときも、DAMP と衝突する慣習（ファクトリ・ビルダー・共有アサーション
ヘルパーの推奨）は書かない。

## architecture.md

`/harness-init` がフェーズ1のディレクトリ構造分析から生成。クリーンアーキ/フロント/レイヤードを判定し、層構造・依存方向・配置ガイドライン・禁止パターンを記述。フラット構造はスキップ。

## workflow.md / debugging.md / memory.md / domain.md

- `workflow.md`: Git/PR規約・並列ディスパッチ・ループ協議。CIコマンドは CLAUDE.md 参照（直書きしない）
- `debugging.md`: 差分診断デバッグ・3ストライク・コンテキスト管理。言語非依存
- `memory.md`: ファイルメモリ運用。言語非依存
- `domain.md`: `/harness-init` が CodeGraph でコードベース調査し実態を埋める
