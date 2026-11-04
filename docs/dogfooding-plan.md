# v2 Dogfooding 導入計画（Wave 17 停止点）

## 1. 目的と停止理由（D13 / D19）

本ドキュメントは `self-evolve-harness` リポジトリ自身を v1 テンプレート構成から v2（`seh` パッケージ + `.harness/spec` 正本 + 4ホスト生成物）へ移行する **Wave 17（T67）計画書**です。

- Dogfooding の適用（`--apply`）は `CLAUDE.md`、`AGENTS.md`、各ホストの Hook 設定（`.claude/settings.json`、`.agents/hooks.json`、`.codex/hooks.json`、`.opencode/plugins/seh-guard.ts`）、Agent 定義、および `.agents/skills` シンボリックリンクの置換を伴う R2 / `USER_OWNED_CONFLICT` 変更です。
- 設計方針（01 §11、02 §10、D13、D19）により、**AI エージェントは自身の設定・Hook・承認境界に対する承認を自己発行できません**。
- そのため、本 Wave で `uv tool install -e .` の実行および `seh init --plan` / `seh migrate plan --from v1` の計画記録までを完了して停止します。

---

## 2. 事前準備（完了済み）

編集可能モードでの CLI 導入を確認済みです。

```bash
uv tool install -e .
seh --version
# => seh 2.0.0a0
```

---

## 3. 生成される `.harness/config.toml`（D13 準拠）

`seh init --hosts all --memory engram --code-intel codegraph --plan` が生成する設定内容は以下のとおりです。

```toml
schema_version = 1
profile = "balanced"

[hosts]
enabled = [
    "claude",
    "antigravity",
    "codex",
    "opencode",
]

[hosts.antigravity]
surface = "auto"
managed_cli = "disabled"

[runtime]
mode = "native"
backend = "cli"
selected_host = "auto"
max_parallel = 2
max_attempts_per_unit = 3
max_seconds_per_unit = 600
max_total_seconds = 3600

[runtime.security]
require_worktree = true
command_allowlist = [
    "git",
    "python",
    "pytest",
]
allow_network = false
trust_external_repo = false

[code_intelligence]
provider = "codegraph"
fallback = "source"

[memory]
provider = "engram"
path = ".agent-memory"

[evaluation]
mode = "required"
trials = 3
promotion_requires_holdout = true

[evolution]
mode = "propose"

[authoring]
policy = "required"
require_eval_for_behavior_change = true
required_hosts = [
    "claude",
    "codex",
    "opencode",
]
require_ci_for_promote = true

[sdk]
enabled = false
```

---

## 4. `seh migrate plan --from v1` の結果（baseline: `4c5ac19`）

v1 baseline（`4c5ac19` / `v1-baseline` タグ）との三者差分に基づく分類結果（全 59 件）:

### 4.1 競合（`USER_OWNED_CONFLICT`：明示承認が必要）— 2 件

| パス | 理由 | 対応方針 |
| --- | --- | --- |
| `.agents/skills` | シンボリックリンク（リンク先: `../.claude/skills`） | `--approve-conflict .agents/skills` で承認し、snapshot 保存のうえリンクを解除して実ディレクトリ（`.agents/skills/{harness-init,work}/`）へ置換する（D9 / D12） |
| `CLAUDE.md` | v1 baseline から `<CI_CHECK_CMD>` / `<CI_FIX_CMD>` プレースホルダが埋め込まれている（現物 sha256: `90818a4f...` / baseline sha256: `5f1a2fa0...`） | `--approve-conflict CLAUDE.md` で承認し、snapshot 保存のうえ v2 の `@AGENTS.md` import ブロックへ置換する（CI コマンドは `.harness/spec/instructions/core.md` に自動反映される） |

### 4.2 保持（`KEEP`：ユーザーデータ・テンプレート）— 4 件

- `.agent-memory/MEMORY.md` — ユーザーデータ（常に保持）
- `.agents/skills.json` — ユーザーデータ（常に保持）
- `.claude/settings.local.json` — ユーザーデータ（常に保持）
- `.github/pull_request_template.md` — v1 から未改変（template）

### 4.3 再生成・移管・削除（`REWRITE` / `MOVE` / `DELETE`：v1 から未改変）— 53 件

- **`REWRITE`（11 件）**:
  - `.claude/.gitignore`
  - `.claude/agents/{evolver,fixer,implementer,reviewer}.md`
  - `.claude/rules/{architecture,coding,testing}.md`
  - `.claude/settings.json`
  - `.claude/skills/harness-init/SKILL.md`
  - `AGENTS.md`
- **`MOVE`（23 件）**:
  - `.claude/_reference.md`（`docs/architecture.md` へ統合済み）
  - `.claude/rules/domain.md`
  - `references/ahe-principles.md`（旧自己進化スキル配下の参照資料）
  - `.claude/skills/harness-init/{languages,memory-backends,shared,task-runners}/**`（`seh init` の Python 検出ロジック・Provider へ移管済み）
- **`DELETE`（19 件）**:
  - `.claude/agents/{ci-triage,design-reviewer,refactorer,researcher,test-writer}.md`
  - `.claude/rules/{debugging,memory,workflow}.md`
  - `.claude/scripts/doctor.sh`
  - `.claude/skills/{address-review,brainstorm,create-pr,create-skill,desloppify,evolve-rules,harness-sync,save-session,self-review}/**`

---

## 5. `seh init --hosts all --memory engram --code-intel codegraph --plan` の結果

### 5.1 検出結果

- ルートアプリ `.`: `python`
  - `CI_CHECK_CMD`: `uv run ruff check . && uv run ruff format --check . && uv run pyright && uv run pytest`
  - `CI_FIX_CMD`: `uv run ruff check --fix . && uv run ruff format .`

### 5.2 配置される正本 spec（10 件）

- `.harness/spec/agents/{evolver,fixer,implementer,reviewer}.yaml`
- `.harness/spec/instructions/core.md`
- `.harness/spec/rules/{engineering,testing}.md`
- `.harness/spec/skills/harness-init/SKILL.md`
- `.harness/spec/skills/work/SKILL.md`
- `.harness/spec/skills/work/references/managed-task.md`

### 5.3 ホスト生成物（v1 移行適用後に書き込まれるファイル）

`apply_migration` によって v1 の未改変ファイルと承認済み競合（`.agents/skills`・`CLAUDE.md`）が整理された後、4 ホスト分の生成物が配置されます（計 44 ファイル書込）:

- **共通 / 正本・管理ファイル**:
  - `.harness/config.toml`
  - `.harness/spec/**`（10 件）
  - `.harness/manifest.json`
  - `.harness/generated.lock.json`
  - `.gitignore`（`# seh:begin ... # seh:end` ブロック追記）
  - `AGENTS.md`（常時指示 + Authoring 規約）
  - `CLAUDE.md`（`@AGENTS.md` import）
- **Claude Code（`host:claude`）**:
  - `.claude/settings.json`（`seh hook` シム + permissions）
  - `.claude/rules/{engineering,testing}.md`
  - `.claude/agents/{evolver,fixer,implementer,reviewer}.md`
  - `.claude/skills/{harness-init,work}/**`
- **Google Antigravity / Codex / OpenCode 共有（`.agents/`）**:
  - `.agents/skills/{harness-init,work}/**`
  - `.agents/rules/{engineering,testing}.md`
  - `.agents/agents/{evolver,fixer,implementer,reviewer}.md`
  - `.agents/hooks.json`
- **Codex CLI（`host:codex`）**:
  - `.codex/agents/{evolver,fixer,implementer,reviewer}.toml`
  - `.codex/hooks.json`
- **OpenCode（`host:opencode`）**:
  - `.opencode/agents/{evolver,fixer,implementer,reviewer}.md`
  - `.opencode/plugins/seh-guard.ts`

> **注記（OpenCode の Skill Discovery 重複について）**:
> OpenCode は `.claude/skills` と `.agents/skills` の両方を探索するため、`SKILL_DISCOVERY_COLLISION`（`WARN`）が報告されます（D5 / ADR-0005）。Managed 実行時は Runner が `OPENCODE_DISABLE_CLAUDE_CODE_SKILLS=1` を自動設定して抑止します。Native 利用時はシェル環境変数で `OPENCODE_DISABLE_CLAUDE_CODE_SKILLS=1` を設定してください。

---

## 6. ユーザー実行手順（対話モードでの `--apply`）

ターミナル（対話 TTY）で本リポジトリのルートから以下のコマンドを実行し、確認プロンプト `適用しますか? [y/N]` に `y` と入力してください。

```bash
seh init \
  --hosts all \
  --memory engram \
  --code-intel codegraph \
  --approve-conflict .agents/skills CLAUDE.md \
  --apply
```

実行が完了すると、`snapshot: <snapshot_id>` と `seh doctor` の結果が表示されます。実行後、セッションを再開（または完了を通知）していただければ **Wave 18（T68: apply 後の証拠収集と最終確認）**へ進みます。

---

## 7. ロールバック・緊急復旧手順（3 段階）

万一 apply 後に Hook の fail-closed 等でツール実行がブロックされた場合は、通常のターミナルから以下のいずれかで即座に復旧できます。

### 手順 A: `seh migrate rollback` による v1 資産の復元

`seh init --apply` が出力した `<snapshot_id>`（`.harness/backups/` 配下）を指定してロールバックします。

```bash
seh migrate rollback <snapshot_id> --root .
```

### 手順 B: `.harness/backups/` のスナップショット一覧からの確認・復元

`<snapshot_id>` が不明な場合は `.harness/backups/` のディレクトリ名（タイムスタンプ順）を確認して復元できます。

```bash
ls -1 .harness/backups/
seh migrate rollback <最新のsnapshot_id> --root .
```

### 手順 C: Git ベースラインタグ（`v1-baseline`）からの完全復旧

`seh` コマンド自体を使わずに Git から直接 v1 状態へ戻す場合:

```bash
git checkout v1-baseline -- .claude CLAUDE.md AGENTS.md .gitignore
rm -rf .harness .codex .opencode .agents/agents .agents/rules .agents/hooks.json .agents/skills
ln -s ../.claude/skills .agents/skills
```

---

## 8. Wave 18（apply 後）の検証項目（T68）

ユーザーの対話 apply 完了後、以下を実施して `docs/dogfooding-report.md` に記録します。

1. `seh doctor --hosts all --context` の PASS と `compatibility.json` の記録
2. stdin JSON による `seh hook <event>` 直接呼び出しの結合確認
3. `seh` 参照監査（削除済み v1 Skill / Agent / Rule 名のダングリング参照 0 件）
4. Skill Discovery 重複状態の確認（Claude / AGY / Codex で 0 件、OpenCode は ADR-0005 の明示 WARN）
5. 生成された `/work` Skill の Authoring Eval（D4 の実 CLI 上限内、不可の場合は `BLOCKED_NO_EVAL` として記録）
6. 一時 clone 上での `seh migrate rollback` 往復検証
