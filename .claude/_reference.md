# .claude/ ハーネス設計 リファレンス

このハーネスの設計で参考にしたリポジトリ、技術、パターンの一覧と使い方ガイド。

---

## 使い方クイックガイド

### 自動で動くもの（何もしなくてOK）

| 機能                   | 仕組み                                                                      |
| ---------------------- | --------------------------------------------------------------------------- |
| ルール適用             | ソース編集時に該当 rules が自動ロード（`/harness-init` が `paths` を生成）          |
| 自動フォーマット       | Write/Edit 後に `/harness-init` が検出したフォーマッタ（PostToolUse フック）       |
| アーキテクチャ違反検知 | `/harness-init` が構造分析から生成した依存方向守衛（PostToolUse フック）            |
| CI ゲート              | git commit 前に `CI_CHECK_CMD` 自動実行（PreToolUse フック）                |
| 破壊的コマンドブロック | rm -rf / 等を自動ブロック（PreToolUse フック）                              |
| 完了前テスト           | タスク完了宣言前に CI を再実行（Stop フック）                               |
| 健全性プローブ         | セッション開始時に engram 不在・settings.local.json 破損を検出し1行警告（SessionStart フック）。詳細は `/doctor` |
| 要件定義ファースト     | コード変更依頼時に `/brainstorm` を自動実行                    |
| feedback 捕捉          | ユーザー発話の修正語を UserPromptSubmit フックが検出し、`[feedback]` の Engram 保存を促す（保存自体はエージェントが実行） |
| feedback メモリ        | ユーザーの修正・指摘直後に即時保存                             |
| project メモリ         | 設計判断で選択肢から1つを選んだとき保存                       |
| セッション保存         | `/create-pr` 後、`/loop` 完了後、セッション終了時に自動実行   |
| ハーネス自動進化       | 未処理 feedback 3件以上で SessionStart フックが evolver エージェントを起動。ルール/スキル/エージェント/hook を自律判定で追加・改修（hook は検証ゲート付き・限定操作） |

### スキル（`/skill-name` で手動呼び出し）

| コマンド         | 用途                                            |
| ---------------- | ----------------------------------------------- |
| `/brainstorm`    | 要件定義。目的→制約→成功基準→設計→承認→実装計画 |
| `/create-pr`     | PRテンプレートに従ってPR作成                    |
| `/self-review`   | YAGNI/KISS/DRY/Fail Fast/可読性の観点でレビュー |
| `/evolve-rules`  | フィードバックからルール/スキル/エージェントを進化 |
| `/save-session`  | 作業コンテキストをメモリに保存                  |
| `/create-skill`  | 新しいスキルを作成・テスト・配置                |
| `/doctor`        | ハーネス自己診断。Engram/CodeGraph到達性・JSON妥当性・ダングリング参照を検査 |
| `/harness-init`          | リポジトリ初期化。スタック検出→hooks/rules生成  |

### エージェント（`Agent(subagent_type: "name")` で呼び出し）

| エージェント      | 用途                                                               |
| ----------------- | ------------------------------------------------------------------ |
| `reviewer`        | コードレビュー。YAGNI/KISS/DRY、アーキテクチャ準拠、型安全性を検証 |
| `test-writer`     | DAMP 原則に従ったテスト生成                                        |
| `refactorer`      | コードの構造改善。reviewer から委譲される                          |
| `design-reviewer` | brainstorm で作成した設計ドキュメントをレビュー                    |
| `fixer`           | 行き詰まり打破。まっさらなコンテキストでゼロから診断               |
| `ci-triage`       | CI失敗を種別分類し委譲先（fixer/refactorer/呼び出し元）を提案。修正はしない |
| `researcher`      | 外部情報調査。WebSearch/WebFetch で出典付き要約を分離コンテキストで返す |
| `evolver`         | ハーネス進化。AUTO-EVOLVE 通知でバックグラウンド起動され、feedback を rules/skills/agents/hook に反映 |

### ループ実行（`/loop` `/goal` で自律実行）

```bash
# 30分ごとにissueをチェックして自動実装
/loop 30m
未処理issueを確認し、あれば workflow.md のループ協議に従い実装する。

# 特定のゴールを達成するまで自律実行
/goal PR #123 が green CI、blocking comment なし、main にリベース済み
```

---

## 参考リポジトリ

### [Picrew/awesome-agent-harness](https://github.com/Picrew/awesome-agent-harness)

Agent Harness に関するリソース（プロジェクト、ツール、ベンチマーク、実践ガイド）を300以上まとめたキュレーションリスト。
9カテゴリ（Harness Architecture、Context Engineering、Execution Substrates、Protocols、Evaluation、Observability、Guardrails、Reference Implementations、Essential Readings）で整理されている。

### [shareAI-lab/learn-claude-code](https://github.com/shareAI-lab/learn-claude-code)

「Bash is all you need」を掲げ、Claude Code のようなエージェントハーネスをゼロから構築する教育用リポジトリ。
全20レッスンで、ツール実装、メモリ管理、サブエージェント、サンドボックス、コンパクションを段階的に学べる。

### [anthropics/skills](https://github.com/anthropics/skills)

Claude Code を拡張するための Anthropic 公式スキルリポジトリ。
SKILL.md フォーマット、references/ による Progressive Disclosure、scripts/ による決定論的自動化、skill-creator メタスキルなどのベストプラクティスを提供。

### [oracle/agent-spec](https://github.com/oracle/agent-spec)

フレームワーク非依存の宣言型エージェント定義言語（Open Agent Spec）。
Agent / Flow / Tool の3要素で構成され、BranchingNode、ParallelFlowNode、MapNode 等のワークフロー制御、JSON Schema ベースの入出力型検証を定義している。

### 参考記事

#### [ループエンジニアリング — 入門から実践まで（Qiita: Syoitu）](https://qiita.com/Syoitu/items/97ed37e7ba9c38dc75d8)

ループエンジニアリングの定義、4層積み上がりモデル（Prompt→Context→Harness→Loop）、5つのアクション（発見・受け渡し・検証・記憶・スケジューリング）。
CLAUDE.md のループ協議、Stop フック、fixer エージェントの3ファイル構成パターンを提供。

#### [Loop Engineering 設計ガイド（Zenn: suwash）](https://zenn.dev/suwash/articles/loop-engineering_20260610)

ループの7特徴、6プリミティブ、自律ティア（L1→L2→L3）の段階的昇格モデル。
Maker-Checker分離、STATE.md による外部状態管理、トークンコストの二次関数的特性と予算管理を体系化。

#### [やさしいループエンジニアリング入門（docswell: harinezumi）](https://www.docswell.com/s/harinezumi/K3J9JJ-2026-07-10-202543)

ループが有効な4条件（反復性、機械的失敗検出、自律完結、客観的完成定義）を明確化。
ループプロトコルを workflow.md のループ協議として体系化し、/loop + /goal で自律実行する実践パターンを提示。

---

## 採用したパターンと出典

### アーキテクチャ & 構造

| パターン                                  | 出典              | 適用先                                    |
| ----------------------------------------- | ----------------- | ----------------------------------------- |
| CLAUDE.md 200行制限 + rules/ 分割         | Claude Code 公式  | `CLAUDE.md`, `.claude/rules/`             |
| paths 指定による条件付きルール読込        | Claude Code 公式  | `.claude/rules/*.md` frontmatter          |
| SKILL.md ディレクトリ形式                 | anthropics/skills | `.claude/skills/*/SKILL.md`               |
| YAML frontmatter + Markdown 本体          | Claude Code 公式  | `.claude/agents/*.md`                     |
| settings.json / settings.local.json 分離  | Claude Code 公式  | `.claude/settings.json`                   |
| references/ による Progressive Disclosure | anthropics/skills | `.claude/skills/evolve-rules/references/` |
| 階層的ルールによる責務分離                | oracle/agent-spec | `.claude/rules/` の領域別分割             |

### 自己進化メカニズム

| パターン                          | 出典                                 | 適用先                         |
| --------------------------------- | ------------------------------------ | ------------------------------ |
| evaluate→analyze→improve ループ   | awesome-agent-harness (auto-harness) | `/evolve-rules`                |
| メモリの Dream 統合               | learn-claude-code                    | `/evolve-rules` メモリ整理     |
| skill-creator メタスキル          | anthropics/skills                    | `/create-skill`                |
| self-evolving memory runtime      | awesome-agent-harness (EverOS)       | メモリ自動運用                 |
| AHE 原則（証拠ベースの改善4項目） | awesome-agent-harness                | `references/ahe-principles.md` |
| レッスンログ昇格（3回→ルール化）  | awesome-agent-harness                | `/evolve-rules`                |
| No-Op テスト（ルール剪定）        | awesome-agent-harness                | `/evolve-rules`                |

### Context Engineering

| パターン                           | 出典              | 適用先                 |
| ---------------------------------- | ----------------- | ---------------------- |
| スキル2層ロード                    | learn-claude-code | Claude Code ネイティブ |
| サブエージェントのコンテキスト分離 | learn-claude-code | `.claude/agents/`      |
| フェーズゲート付きリソース読込     | anthropics/skills | `/brainstorm`          |

### Prompt Engineering

| パターン                                 | 出典                  | 適用先         |
| ---------------------------------------- | --------------------- | -------------- |
| 合理化テーブル                           | awesome-agent-harness | `coding.md`    |
| 3ストライクエラープロトコル              | awesome-agent-harness | `debugging.md` |
| Evidence-Before-Assertion                | awesome-agent-harness | `workflow.md`  |
| スコープ規律（NOTICED BUT NOT TOUCHING） | awesome-agent-harness | `coding.md`    |
| サイレント成功・冗長失敗                 | awesome-agent-harness | `debugging.md` |
| 差分診断デバッグ                         | awesome-agent-harness | `debugging.md` |
| HARD-GATE（実装行為の絶対禁止）          | anthropics/skills     | `/brainstorm`  |
| WIP ファーストコミット規律               | awesome-agent-harness | `workflow.md`  |

### テスト設計

| パターン                     | 出典                   | 適用先       |
| ---------------------------- | ---------------------- | ------------ |
| DAMP 原則                    | ソフトウェアテスト一般 | `testing.md` |
| AAA パターン                 | ソフトウェアテスト一般 | `testing.md` |
| fixture 最小化・ヘルパー禁止 | プロジェクト方針       | `testing.md` |

### エージェント設計

| パターン                             | 出典                          | 適用先                       |
| ------------------------------------ | ----------------------------- | ---------------------------- |
| Swarm パターン（エージェント間委譲） | oracle/agent-spec             | reviewer → refactorer        |
| ManagerWorkers パターン              | oracle/agent-spec             | brainstorm → design-reviewer |
| 偵察→行動パターン                    | anthropics/skills             | refactorer, test-writer      |
| Maker-Checker 分離                   | Qiita (Syoitu), Zenn (suwash) | 作業エージェント + fixer     |

### Hooks & Automation

| パターン                              | 出典                  | 適用先                          |
| ------------------------------------- | --------------------- | ------------------------------- |
| PostToolUse（自動フォーマット）       | learn-claude-code     | `/harness-init` が検出したフォーマッタ    |
| PostToolUse（アーキテクチャ違反検知） | awesome-agent-harness | `/harness-init` が生成した依存方向守衛    |
| PreToolUse（破壊的コマンドブロック）  | learn-claude-code     | rm -rf 等                       |
| PreToolUse（CI 品質ゲート）           | awesome-agent-harness | git commit 前の `CI_CHECK_CMD`  |
| Stop フック（完了前テスト）           | Qiita (Syoitu)        | タスク完了前の CI 再実行        |

### ループエンジニアリング

| パターン                                  | 出典                  | 適用先                         |
| ----------------------------------------- | --------------------- | ------------------------------ |
| ループ協議（停止条件・最大試行回数）      | Qiita (Syoitu)        | CLAUDE.md ループ協議セクション |
| 停止条件3層（目標達成・超過・行き詰まり） | docswell (harinezumi) | `workflow.md`（ループ協議）    |
| fixer エージェント（行き詰まり打破）      | Qiita (Syoitu)        | `.claude/agents/fixer.md`      |
| 4層積み上がりモデル                       | Qiita (Syoitu)        | 全体設計思想                   |
| 自律ティア（L1→L2→L3）                    | Zenn (suwash)         | 段階的昇格の参考               |
| メモリ必須（ループ中の作業記録）          | docswell (harinezumi) | CLAUDE.md メモリ自動運用       |

### セキュリティ & ガードレール

| パターン                                         | 出典              | 適用先                      |
| ------------------------------------------------ | ----------------- | --------------------------- |
| 3段階ゲート（Hard Deny → Rule Match → Approval） | learn-claude-code | PreToolUse フック           |
| Gotchas セクション                               | anthropics/skills | `domain.md`                 |
| アサーション削除・テスト弱体化の禁止             | Qiita (Syoitu)    | CLAUDE.md, `workflow.md`    |

---

## ファイル構成

```
CLAUDE.md                                    # コア原則 + 自動動作（≤200行）。/harness-init がプレースホルダを埋める
AGENTS.md                                    # サブエージェント共通の行動規範（言語非依存の完成形）
.claude/
├── rules/
│   ├── architecture.md                      # `/harness-init` が構造分析から生成（paths: src/**)
│   ├── coding.md                            # 汎用骨格 + `/harness-init` が言語固有を埋める（paths: src/**, scripts/**)
│   ├── testing.md                           # 汎用骨格 + `/harness-init` が言語固有を埋める（paths: tests/**)
│   ├── debugging.md                         # デバッグ規約（paths: src/**, scripts/**, tests/**)
│   ├── workflow.md                          # Git・PR規約
│   └── domain.md                            # `/harness-init` が CodeGraph で生成 + Gotchas
├── agents/
│   ├── reviewer.md                          # コードレビュー → refactorer に委譲可
│   ├── test-writer.md                       # DAMP テスト生成
│   ├── refactorer.md                        # 構造改善
│   ├── design-reviewer.md                   # 設計ドキュメントレビュー
│   ├── fixer.md                             # 行き詰まり打破（model: opus）
│   ├── ci-triage.md                         # CI失敗トリアージ → fixer/refactorer 委譲提案
│   ├── researcher.md                        # 外部情報調査（WebSearch/WebFetch）
│   └── evolver.md                           # ハーネス進化（バックグラウンド）
├── skills/
│   ├── brainstorm/SKILL.md                  # 要件定義（HARD-GATE 付き）
│   ├── create-pr/SKILL.md                   # PR作成
│   ├── self-review/SKILL.md                 # セルフレビュー（自己完結型）
│   ├── evolve-rules/                        # ルール進化
│   │   ├── SKILL.md
│   │   └── references/ahe-principles.md     # AHE 原則
│   ├── save-session/SKILL.md                # セッション保存
│   ├── create-skill/SKILL.md                # メタスキル
│   ├── doctor/SKILL.md                      # ハーネス自己診断
│   └── harness-init/SKILL.md                        # リポジトリ初期化
├── settings.json                            # チーム共通設定 + hooks
├── settings.local.json                      # 個人設定（.gitignore）
└── _reference.md                            # このファイル
```

---

## Claude Code 公式ドキュメント

- **CLAUDE.md**: 毎セッション自動読込。200行以下推奨。
- **`.claude/rules/`**: `paths:` でファイル編集時に自動適用。
- **`.claude/agents/`**: YAML frontmatter + Markdown。`Agent(subagent_type: "name")` で呼び出し。
- **`.claude/skills/*/SKILL.md`**: `/skill-name` で呼び出し。references/ と scripts/ 同梱可。
- **`.claude/settings.json`**: Git管理。permissions + hooks。
- **`.claude/settings.local.json`**: .gitignore。個人設定。
