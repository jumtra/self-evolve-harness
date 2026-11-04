# self-evolve-harness v2.0 設計文書セット（CLI First / SDK Optional・v1.3）

更新日: 2026-11-04  
状態: **設計提案・未実装（元GitHubリポジトリは変更していません）**

## 対応範囲

- Claude Code・Codex・OpenCode・Google Antigravity（AGY）の**設定・Skill・Promptのネイティブ形式を生成**する。
- **公式CLIをManaged Runtimeの標準バックエンドに使用**する。Python/TypeScript Agent SDKパッケージは初期導入不要。
- CLI RunnerはClaude `claude -p`、Codex `codex exec`、OpenCode `opencode run`。AGYは`agy -p`自体に公式ヘッドレス機能があるが、**個人向けプランの第三者ラッピング制約**があるため外部Managed実行は既定`POLICY_BLOCKED`。
- Native/Managedを分離。ManagedではPythonがDAG・検証・局所修正・予算・チェックポイントを制御し、CLI内部のTool呼出しはホストが制御する。
- Eval-first、Skill/Prompt最小化、CodeGraph/Graphify選択、4ホストの設定生成、自己進化の承認/ロールバックを維持。

## 読む順番

1. [01_改修方針書.md](01_改修方針書.md) — 削除・統合とCLI First方針
2. [02_要件定義書.md](02_要件定義書.md) — FR-001〜FR-100、各環境の受け入れ基準
3. [03_実装計画書.md](03_実装計画書.md) — Phase 0〜8、CLI Runner実装順序
4. [04_Skill・Prompt作成標準.md](04_Skill・Prompt作成標準.md) — 動画のメソッド、Authoring Guard/Eval
5. [05_マルチホスト互換性・実行設計.md](05_マルチホスト互換性・実行設計.md) — Host Adapterの互換性
6. [06_CLIランナー・SDK任意化設計.md](06_CLIランナー・SDK任意化設計.md) — **新規：CLIコマンド、Runner契約、AGY契約制約、E2Eテスト**

## v1.2 → v1.3 主な変更

| 項目 | v1.2 | v1.3 |
|---|---|---|
| Managed実行 | SDK/CLIの混合 | **CLI標準、SDKパッケージ不要** |
| AgentRunner | SDKセッション前提の操作含む | **1コマンド実行`run_once`、継続/streamはオプションCapability** |
| SDK依存 | Host別追加を想定 | **インストール不要。将来の明示的任意拡張のみ** |
| AGY | 外部Runner利用を想定 | **Managed既定`POLICY_BLOCKED`、Native設定生成は可能** |
| 安全性 | 設計上の権限管理 | **OS隔離・Worktree・Policy・CIを重ねてCLI内部Toolを制約** |
| E2E | SDKまたはCLI | **Mock subprocess + 実CLI（適切な資格・認証を前提）** |

## サンプル

- [examples/multi_host.config.example.toml](examples/multi_host.config.example.toml)
- [examples/AGENTS.authoring.snippet.md](examples/AGENTS.authoring.snippet.md)
- [examples/CLAUDE.authoring.snippet.md](examples/CLAUDE.authoring.snippet.md)
- [examples/authoring_policy.toml](examples/authoring_policy.toml)
- [examples/prompt_skill_eval_cases.example.json](examples/prompt_skill_eval_cases.example.json)

## 確認した一次資料

- Claude CLI: https://code.claude.com/docs/en/headless
- Codex CLI: https://learn.chatgpt.com/docs/non-interactive-mode
- OpenCode CLI: https://opencode.ai/docs/cli/
- AGY CLI: https://antigravity.google/docs/cli/headless/
- AGY利用条件: https://antigravity.google/docs/faq

**注意**: CLIのフラグ・サポートはインストールされたバージョンの`--help`/probeで実装時に再確認する。本パッケージは設計書と設定例であり、動作するハーネス実装ではない。
