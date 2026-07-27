# self-evolve-harness

Claude Code 用の**自己進化型ハーネス**テンプレート。任意のプロジェクトに `.claude/` を投入し、
`/harness-init` を実行すると、言語・ツール・構造を自動検出してルール・フック・ドメイン知識・
CLAUDE.md/AGENTS.md を生成する。以降はユーザーのフィードバックを Engram（記憶層）に蓄積し、
ハーネス自身（ルール/スキル/エージェント/フック）を自律的に改善していく。

## 何が入っているか

| 種別 | 内容 |
|------|------|
| `CLAUDE.md` / `AGENTS.md` | コア原則・ワークフロー・サブエージェント行動規範（`/harness-init` がプレースホルダを埋める） |
| `.claude/rules/` | coding / testing / architecture / debugging / workflow / memory / domain の規約（`paths` で自動適用） |
| `.claude/skills/` | `/brainstorm` `/harness-init` `/evolve-rules` `/doctor` `/create-pr` `/address-review` `/self-review` `/create-skill` `/save-session` 等 |
| `.claude/agents/` | implementer / reviewer / test-writer / refactorer / design-reviewer / fixer / ci-triage / researcher / evolver |
| `.claude/settings.json` | 言語非依存の安全フック（破壊コマンド/機密/設定保護ブロック・秘密情報スキャン・AUTO-EVOLVE・健全性プローブ・FB捕捉・実行ログ） |
| `.github/pull_request_template.md` | PRテンプレート（`workflow.md` の4セクション規定の実体） |

設計思想と各パターンの出典は [`.claude/_reference.md`](.claude/_reference.md) を参照。

## 導入手順

### 1. `.claude/` と CLAUDE.md/AGENTS.md を対象プロジェクトにコピー

```sh
cp -r self-evolve-harness/.claude self-evolve-harness/CLAUDE.md self-evolve-harness/AGENTS.md <your-project>/
```

### 2. 必須ツールを導入（記憶層・コードグラフ）

- **Engram**（セッション記憶層・SQLite + FTS5・外部 API 不要）: GitHub Releases から
  バイナリを `~/.local/bin/engram` に配置
- **CodeGraph**（コードナレッジグラフ）: `curl -fsSL https://raw.githubusercontent.com/colbymchenry/codegraph/main/install.sh | sh`

いずれも `~/.claude.json` の `mcpServers` に stdio MCP として登録する（詳細は `/harness-init` 手順5が自動で案内）。

> エンタープライズで marketplace プラグインがブロックされる環境向けに、stdio MCP を直接登録する方針。

### 3. `/harness-init` を実行

Claude Code で対象プロジェクトを開き、`/harness-init` を実行する。スタック検出 → 生成内容の提示 →
**ユーザー承認** → 生成、の順で進む（承認前に環境やリポジトリを書き換えない）。

### 4. 使い始める

- コード変更依頼 → `/brainstorm` が要件定義→計画→自律実行を仕切る。計画時に wave（並列グループ）が
  割られ、承認後は wave 単位で `implementer` を並列ディスパッチして無質問で完遂する
- PR のレビュー指摘 → `/address-review` が分類→承認→修正→再push→解決報告まで運ぶ
- 環境が怪しいとき → `/doctor` で自己診断（実行ログの内訳も確認できる）
- フィードバックが溜まると（3件以上）セッション開始時に自動で evolver が起動しハーネスを改善

## 前提

- Claude Code（CLI / IDE 拡張いずれか）
- 記憶・進化機能を使うには Engram が必要（未導入時は該当機能が劣化）
- ルール・ドキュメントは日本語

## 状態

個人利用・検証用のハーネス。`/harness-init` のエンドツーエンド自動テストは未整備のため、
新規プロジェクトへ適用した際は生成結果（`settings.json` / rules / CLAUDE.md）を目視確認すること。
