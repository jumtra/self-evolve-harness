# self-evolve-harness

Claude Code 用の**自己進化型ハーネス**テンプレート。任意のプロジェクトに `.claude/` を投入し、
`/harness-init` を実行すると、言語・ツール・構造を自動検出してルール・フック・ドメイン知識・
CLAUDE.md/AGENTS.md を生成する。以降はユーザーのフィードバックを記憶層
（`/harness-init` で選択式: リポジトリローカルのファイルメモリ `.agent-memory/`、
または Engram MCP）に蓄積し、ハーネス自身（ルール/スキル/エージェント/フック）を自律的に改善していく。
`/harness-sync` で `.claude/` を正本として AGENTS.md / `.opencode/` 向けに変換生成でき、
Codex・OpenCode などと1リポジトリ内で共有して使える。

## 何が入っているか

| 種別 | 内容 |
|------|------|
| `CLAUDE.md` / `AGENTS.md` | コア原則・ワークフロー・サブエージェント行動規範（`/harness-init` がプレースホルダを埋める） |
| `.claude/rules/` | coding / testing / architecture / debugging / workflow / memory / domain の規約（`paths` で自動適用） |
| `.claude/skills/` | `/brainstorm`（detail/simple 2モード） `/harness-init` `/harness-sync` `/evolve-rules` `/create-pr` `/address-review` `/self-review` `/create-skill` `/save-session` 等 |
| `.claude/agents/` | implementer / reviewer / test-writer / refactorer / design-reviewer / fixer / ci-triage / researcher / evolver |
| `.claude/settings.json` | 言語非依存の安全フック（破壊コマンド/機密/設定保護ブロック・秘密情報スキャン・AUTO-EVOLVE・健全性プローブ・FB捕捉・実行ログ） |
| `.github/pull_request_template.md` | PRテンプレート（`workflow.md` の4セクション規定の実体） |

設計思想と各パターンの出典は [`.claude/_reference.md`](.claude/_reference.md) を参照。

## 導入手順

### 1. `.claude/` と CLAUDE.md/AGENTS.md/PRテンプレート/`.agent-memory/` を対象プロジェクトにコピー

```sh
cp -r self-evolve-harness/.claude self-evolve-harness/CLAUDE.md self-evolve-harness/AGENTS.md self-evolve-harness/.agent-memory <your-project>/
mkdir -p <your-project>/.github
cp self-evolve-harness/.github/pull_request_template.md <your-project>/.github/
```

`.claude/.gitignore` が同梱されているので、実行ログ（`harness-log.jsonl`）・個人設定
（`settings.local.json`）・worktree は導入先でも自動的に除外される（ルートの `.gitignore` への
追記は不要）。

### 2. 必須ツールを導入（コードグラフ）

記憶層は `/harness-init` で選択（file バックエンド既定・導入不要。Engram MCP も選択可）。

- **CodeGraph**（コードナレッジグラフ）: `curl -fsSL https://raw.githubusercontent.com/colbymchenry/codegraph/main/install.sh | sh`

`~/.claude.json` の `mcpServers` に stdio MCP として登録する（詳細は `/harness-init` 手順5が自動で案内）。

> エンタープライズで marketplace プラグインがブロックされる環境向けに、stdio MCP を直接登録する方針。

### 3. `/harness-init` を実行

Claude Code で対象プロジェクトを開き、`/harness-init` を実行する。スタック検出 → 生成内容の提示 →
**ユーザー承認** → 生成、の順で進む（承認前に環境やリポジトリを書き換えない）。

既に `.claude/` や CLAUDE.md/AGENTS.md があるプロジェクトにも**重ね掛けで適用できる**:
既存ファイルは保持したまま、競合内容と差分（skills/agents は既存保持・rules は空欄のみ補完・
hooks は追加マージ）を提示してから適用する。手順1のコピーも既存ファイルは上書きしないように
確認しながら行うこと（`cp -r` の代わりに不足分だけコピーする）。

### 4. 使い始める

- コード変更依頼 → `/brainstorm` がモード選択（detail: 要件定義→計画→自律実行 /
  simple: 一問一答の確認→実装）を聞いてから仕切る。detail では計画時に wave（並列グループ）が
  割られ、承認後は wave 単位で `implementer` を並列ディスパッチして無質問で完遂する
- Codex / OpenCode などでも同じリポジトリを使うとき → `/harness-sync` が `.claude/` を正本に
  AGENTS.md 同期ブロックと `.opencode/agent`・`.opencode/command` を生成する。
  記憶（file バックエンドの `.agent-memory/`）はそのまま全ツールで共有される
- PR のレビュー指摘 → `/address-review` が分類→承認→修正→再push→解決報告まで運ぶ
- 環境が怪しいとき → `bash .claude/scripts/doctor.sh` で自己診断（実行ログの内訳も確認できる）
- フィードバックが溜まると（3件以上）セッション開始時に自動で evolver が起動しハーネスを改善

## 前提

- Claude Code（CLI / IDE 拡張いずれか）
- ルール・ドキュメントは日本語

## 状態

個人利用・検証用のハーネス。`/harness-init` のエンドツーエンド自動テストは未整備のため、
新規プロジェクトへ適用した際は生成結果（`settings.json` / rules / CLAUDE.md）を目視確認すること。
