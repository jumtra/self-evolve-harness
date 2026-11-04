# v1 資産棚卸し

- 基準: コミット `988a019`（v1 最終コミット。後で `v1-baseline` タグが付く）
- 目的: v1 の全資産と参照関係を把握し、移行（T22）と参照監査（T24）の入力にする。機械可読な正本は `src/seh/migration/v1_known_paths.json`（各ファイルの sha256 と `v2_action` を持つ）。
- 根拠: `docs/design/v2/01_改修方針書.md` §2〜4、`docs/specs/2026-11-04-v2-harness-requirements.md` D9 / D12 / D14。
- 本ファイルは参照監査の除外パス（D14）なので、旧 Skill / Agent / Rule 名が現れてよい。

## 1. ファイル一覧（49 件）

対象は 988a019 で git 追跡されている `.claude/**`、`CLAUDE.md`、`AGENTS.md`、`.github/pull_request_template.md`。`.claude/settings.local.json`、`.claude/harness-log.jsonl`、`.claude/worktrees/` は追跡外（`.claude/.gitignore` で除外）なので含めない。

種別: skill / agent / rule / hook_config（settings.json）/ instructions（CLAUDE.md, AGENTS.md）/ reference（参照資料）/ template / other。

| パス | 種別 | v2 での扱い |
| --- | --- | --- |
| `.claude/.gitignore` | other | REWRITE |
| `.claude/_reference.md` | reference | MOVE |
| `.claude/agents/ci-triage.md` | agent | DELETE |
| `.claude/agents/design-reviewer.md` | agent | DELETE |
| `.claude/agents/evolver.md` | agent | REWRITE |
| `.claude/agents/fixer.md` | agent | REWRITE |
| `.claude/agents/implementer.md` | agent | REWRITE |
| `.claude/agents/refactorer.md` | agent | DELETE |
| `.claude/agents/researcher.md` | agent | DELETE |
| `.claude/agents/reviewer.md` | agent | REWRITE |
| `.claude/agents/test-writer.md` | agent | DELETE |
| `.claude/rules/architecture.md` | rule | REWRITE |
| `.claude/rules/coding.md` | rule | REWRITE |
| `.claude/rules/debugging.md` | rule | DELETE |
| `.claude/rules/domain.md` | rule | MOVE |
| `.claude/rules/memory.md` | rule | DELETE |
| `.claude/rules/testing.md` | rule | REWRITE |
| `.claude/rules/workflow.md` | rule | DELETE |
| `.claude/settings.json` | hook_config | REWRITE |
| `.claude/skills/address-review/SKILL.md` | skill | DELETE |
| `.claude/skills/brainstorm/SKILL.md` | skill | DELETE |
| `.claude/skills/brainstorm/references/parallel-dispatch.md` | reference | DELETE |
| `.claude/skills/create-pr/SKILL.md` | skill | DELETE |
| `.claude/skills/create-skill/SKILL.md` | skill | DELETE |
| `.claude/skills/desloppify/SKILL.md` | skill | DELETE |
| `.claude/skills/doctor/SKILL.md` | skill | DELETE |
| `.claude/skills/evolve-rules/SKILL.md` | skill | DELETE |
| `.claude/skills/evolve-rules/references/ahe-principles.md` | reference | MOVE |
| `.claude/skills/harness-init/SKILL.md` | skill | REWRITE |
| `.claude/skills/harness-init/languages/_generic.md` | reference | MOVE |
| `.claude/skills/harness-init/languages/go.md` | reference | MOVE |
| `.claude/skills/harness-init/languages/java.md` | reference | MOVE |
| `.claude/skills/harness-init/languages/node.md` | reference | MOVE |
| `.claude/skills/harness-init/languages/python.md` | reference | MOVE |
| `.claude/skills/harness-init/languages/rust.md` | reference | MOVE |
| `.claude/skills/harness-init/languages/terraform.md` | reference | MOVE |
| `.claude/skills/harness-init/shared/hooks-boilerplate.md` | reference | MOVE |
| `.claude/skills/harness-init/shared/rules-skeleton.md` | reference | MOVE |
| `.claude/skills/harness-init/task-runners/_generic.md` | reference | MOVE |
| `.claude/skills/harness-init/task-runners/cargo.md` | reference | MOVE |
| `.claude/skills/harness-init/task-runners/just.md` | reference | MOVE |
| `.claude/skills/harness-init/task-runners/make.md` | reference | MOVE |
| `.claude/skills/harness-init/task-runners/moon.md` | reference | MOVE |
| `.claude/skills/harness-init/task-runners/npm-scripts.md` | reference | MOVE |
| `.claude/skills/save-session/SKILL.md` | skill | DELETE |
| `.claude/skills/self-review/SKILL.md` | skill | DELETE |
| `.github/pull_request_template.md` | template | KEEP |
| `AGENTS.md` | instructions | REWRITE |
| `CLAUDE.md` | instructions | REWRITE |

集計: KEEP 1 / REWRITE 12 / MOVE 18 / DELETE 18（合計 49）

v2_action の意味:

- KEEP: v2 でも内容を維持する。
- REWRITE: 同じパスまたは同じ役割で v2 の内容に書き換える（生成物化を含む）。
- MOVE: 内容の知見を別の場所（`.harness/knowledge/`、`seh` のコード、`docs/`）へ移し、元のファイルは残さない。
- DELETE: 機能を `seh` / 他の Agent へ統合し、ファイルを削除する。

分類の根拠:

- Skill: 公開は `/harness-init`（REWRITE）と `/work`（新規）の 2 種（01 §2）。他は DELETE。`desloppify` と `doctor` は設計書に無いローカル資産で、D9 により DELETE（`doctor` は `seh doctor` に置換）。
- `harness-init` 配下の `languages/` `task-runners/` `shared/` は、検出ロジックを `seh init`（T15）へコード化するため MOVE。`evolve-rules/references/ahe-principles.md` は evolution エンジンの知見として MOVE。`brainstorm/references/parallel-dispatch.md` は `/work` とワークフローエンジンに置き換わるため DELETE。
- Agent: `implementer` `reviewer` `fixer` `evolver` を維持（REWRITE）、他 5 件は DELETE（01 §3）。
- Rule: `coding` は `engineering.md` へ統合、`testing` は簡潔化、`architecture` は条件付き生成（いずれも REWRITE）。`domain` は `.harness/knowledge/domain.md` へ MOVE。`debugging` `workflow` `memory` は DELETE（01 §4）。
- `.claude/settings.json` は個別 Shell Hook を `seh hook <event>` に集約する薄いシムへ REWRITE。`CLAUDE.md` / `AGENTS.md` は管理ブロックのみ更新する REWRITE。`.claude/.gitignore` は D14a により REWRITE。
- `.claude/_reference.md` は `docs/architecture.md` へ統合（MOVE。要件 D 節の P8 記述）。
- `.github/pull_request_template.md` は残す（KEEP）。
- `harness-sync` スキルと `.claude/scripts/doctor.sh` は 988a019 にもローカルにも存在しない（D9）。移行対象外で、`seh sync` / `seh doctor` は新規実装。

## 2. 相互参照表

各 Skill / Agent / Rule の名前が、どのファイルから参照されているか。

- 手順: 988a019 の全追跡ファイル内容に対する名前一致（`git grep` 相当）。Skill は `/<name>` または `` `<name>` ``、Agent は単語境界つきの名前、Rule は `<name>.md` または `[[<name>]]`。自分自身と `docs/` 配下は除く。
- 近似: 一般語と重なる名前（`fixer` `reviewer` など）は文脈の異なる言及を含みうる。実参照の確定は T24 の監査実装で行う。
- `README.md` は棚卸し対象（`.claude/**` 等）外だが、参照元として列挙する。v2 で README の更新が必要（要件の完了条件）。

### Skill

| 名前 | v2 | 参照元 |
| --- | --- | --- |
| `address-review` | DELETE | `.claude/_reference.md`<br>`README.md` |
| `brainstorm` | DELETE | `.claude/_reference.md`<br>`.claude/rules/workflow.md`<br>`.claude/skills/self-review/SKILL.md`<br>`AGENTS.md`<br>`CLAUDE.md`<br>`README.md` |
| `create-pr` | DELETE | `.claude/_reference.md`<br>`.claude/rules/memory.md`<br>`.claude/skills/address-review/SKILL.md`<br>`.claude/skills/brainstorm/SKILL.md`<br>`.claude/skills/save-session/SKILL.md`<br>`README.md` |
| `create-skill` | DELETE | `.claude/_reference.md`<br>`.claude/skills/evolve-rules/SKILL.md`<br>`README.md` |
| `desloppify` | DELETE | `.claude/skills/harness-init/SKILL.md`<br>`.claude/skills/self-review/SKILL.md` |
| `doctor` | DELETE | `.claude/_reference.md`<br>`.claude/agents/ci-triage.md`<br>`.claude/settings.json`<br>`.claude/skills/harness-init/shared/hooks-boilerplate.md`<br>`CLAUDE.md`<br>`README.md` |
| `evolve-rules` | DELETE | `.claude/_reference.md`<br>`.claude/agents/evolver.md`<br>`.claude/rules/memory.md`<br>`.claude/skills/doctor/SKILL.md`<br>`CLAUDE.md`<br>`README.md` |
| `harness-init` | REWRITE | `.claude/_reference.md`<br>`.claude/agents/evolver.md`<br>`.claude/rules/architecture.md`<br>`.claude/rules/coding.md`<br>`.claude/rules/domain.md`<br>`.claude/rules/testing.md`<br>`.claude/rules/workflow.md`<br>`.claude/skills/doctor/SKILL.md`<br>`.claude/skills/evolve-rules/SKILL.md`<br>`.claude/skills/harness-init/languages/_generic.md`<br>`.claude/skills/harness-init/languages/node.md`<br>`.claude/skills/harness-init/languages/python.md`<br>`.claude/skills/harness-init/shared/hooks-boilerplate.md`<br>`.claude/skills/harness-init/shared/rules-skeleton.md`<br>`CLAUDE.md`<br>`README.md` |
| `save-session` | DELETE | `.claude/_reference.md`<br>`.claude/rules/memory.md`<br>`.claude/skills/address-review/SKILL.md`<br>`.claude/skills/create-pr/SKILL.md`<br>`.claude/skills/doctor/SKILL.md`<br>`README.md` |
| `self-review` | DELETE | `.claude/_reference.md`<br>`.claude/rules/workflow.md`<br>`.claude/skills/brainstorm/SKILL.md`<br>`README.md` |

### Agent

| 名前 | v2 | 参照元 |
| --- | --- | --- |
| `ci-triage` | DELETE | `.claude/_reference.md`<br>`.claude/skills/brainstorm/SKILL.md`<br>`.claude/skills/brainstorm/references/parallel-dispatch.md`<br>`AGENTS.md`<br>`README.md` |
| `design-reviewer` | DELETE | `.claude/_reference.md`<br>`.claude/skills/brainstorm/SKILL.md`<br>`README.md` |
| `evolver` | REWRITE | `.claude/_reference.md`<br>`.claude/rules/memory.md`<br>`.claude/settings.json`<br>`.claude/skills/evolve-rules/SKILL.md`<br>`AGENTS.md`<br>`CLAUDE.md`<br>`README.md` |
| `fixer` | REWRITE | `.claude/_reference.md`<br>`.claude/agents/ci-triage.md`<br>`.claude/agents/implementer.md`<br>`.claude/rules/workflow.md`<br>`.claude/skills/brainstorm/SKILL.md`<br>`.claude/skills/brainstorm/references/parallel-dispatch.md`<br>`.claude/skills/desloppify/SKILL.md`<br>`.claude/skills/evolve-rules/SKILL.md`<br>`AGENTS.md`<br>`CLAUDE.md`<br>`README.md` |
| `implementer` | REWRITE | `.claude/_reference.md`<br>`.claude/rules/workflow.md`<br>`.claude/skills/brainstorm/SKILL.md`<br>`.claude/skills/brainstorm/references/parallel-dispatch.md`<br>`.claude/skills/evolve-rules/SKILL.md`<br>`CLAUDE.md`<br>`README.md` |
| `refactorer` | DELETE | `.claude/_reference.md`<br>`.claude/agents/ci-triage.md`<br>`.claude/agents/implementer.md`<br>`.claude/agents/reviewer.md`<br>`.claude/skills/brainstorm/SKILL.md`<br>`AGENTS.md`<br>`README.md` |
| `researcher` | DELETE | `.claude/_reference.md`<br>`AGENTS.md`<br>`README.md` |
| `reviewer` | REWRITE | `.claude/_reference.md`<br>`.claude/agents/ci-triage.md`<br>`.claude/agents/refactorer.md`<br>`.claude/rules/workflow.md`<br>`.claude/skills/brainstorm/SKILL.md`<br>`.claude/skills/desloppify/SKILL.md`<br>`.claude/skills/evolve-rules/SKILL.md`<br>`.claude/skills/self-review/SKILL.md`<br>`README.md` |
| `test-writer` | DELETE | `.claude/_reference.md`<br>`.claude/agents/implementer.md`<br>`.claude/rules/workflow.md`<br>`README.md` |

### Rule

| 名前 | v2 | 参照元 |
| --- | --- | --- |
| `architecture` | REWRITE | `.claude/_reference.md`<br>`.claude/agents/design-reviewer.md`<br>`.claude/agents/implementer.md`<br>`.claude/agents/reviewer.md`<br>`.claude/skills/brainstorm/references/parallel-dispatch.md`<br>`.claude/skills/harness-init/SKILL.md`<br>`.claude/skills/harness-init/shared/rules-skeleton.md`<br>`.claude/skills/self-review/SKILL.md`<br>`CLAUDE.md` |
| `coding` | REWRITE | `.claude/_reference.md`<br>`.claude/agents/ci-triage.md`<br>`.claude/agents/implementer.md`<br>`.claude/rules/testing.md`<br>`.claude/rules/workflow.md`<br>`.claude/skills/brainstorm/SKILL.md`<br>`.claude/skills/brainstorm/references/parallel-dispatch.md`<br>`.claude/skills/harness-init/SKILL.md`<br>`.claude/skills/harness-init/shared/rules-skeleton.md`<br>`AGENTS.md`<br>`CLAUDE.md` |
| `debugging` | DELETE | `.claude/_reference.md`<br>`.claude/skills/evolve-rules/SKILL.md`<br>`.claude/skills/harness-init/SKILL.md`<br>`.claude/skills/harness-init/shared/rules-skeleton.md`<br>`AGENTS.md`<br>`CLAUDE.md` |
| `domain` | MOVE | `.claude/_reference.md`<br>`.claude/rules/memory.md`<br>`.claude/skills/doctor/SKILL.md`<br>`.claude/skills/harness-init/SKILL.md`<br>`.claude/skills/harness-init/shared/rules-skeleton.md`<br>`CLAUDE.md` |
| `memory` | DELETE | `.claude/settings.json`<br>`.claude/skills/doctor/SKILL.md`<br>`.claude/skills/evolve-rules/SKILL.md`<br>`.claude/skills/harness-init/SKILL.md`<br>`.claude/skills/harness-init/shared/hooks-boilerplate.md`<br>`.claude/skills/harness-init/shared/rules-skeleton.md`<br>`.claude/skills/save-session/SKILL.md`<br>`CLAUDE.md` |
| `testing` | REWRITE | `.claude/_reference.md`<br>`.claude/agents/implementer.md`<br>`.claude/agents/reviewer.md`<br>`.claude/agents/test-writer.md`<br>`.claude/skills/brainstorm/references/parallel-dispatch.md`<br>`.claude/skills/harness-init/SKILL.md`<br>`.claude/skills/harness-init/shared/rules-skeleton.md`<br>`.claude/skills/self-review/SKILL.md`<br>`CLAUDE.md` |
| `workflow` | DELETE | `.claude/_reference.md`<br>`.claude/agents/ci-triage.md`<br>`.claude/agents/implementer.md`<br>`.claude/agents/researcher.md`<br>`.claude/skills/address-review/SKILL.md`<br>`.claude/skills/brainstorm/SKILL.md`<br>`.claude/skills/brainstorm/references/parallel-dispatch.md`<br>`.claude/skills/harness-init/SKILL.md`<br>`.claude/skills/harness-init/shared/rules-skeleton.md`<br>`.claude/skills/self-review/SKILL.md`<br>`AGENTS.md`<br>`CLAUDE.md`<br>`README.md` |

## 3. settings.json の Hook 一覧（10 件）

すべて `type: command` のインライン Shell。

| # | イベント | matcher | 目的 | ブロック |
| --- | --- | --- | --- | --- |
| 1 | SessionStart | startup | 未処理 `[feedback]` が 3 件以上なら AUTO-EVOLVE 通知（Engram 検索） | しない |
| 2 | SessionStart | startup | 環境健全性プローブ（engram 未検出、settings.local.json の JSON 不正を警告） | しない |
| 3 | SessionStart | startup | `session_start` を `.claude/harness-log.jsonl` に記録 | しない |
| 4 | UserPromptSubmit | （なし） | 発話の修正語（違う・直して 等）を単語一致で検出し、フィードバック保存を促す | しない |
| 5 | PreToolUse | Bash | 破壊的コマンド（ルート・ホームへの再帰削除、管理者権限昇格 等）をブロック | exit 2 |
| 6 | PreToolUse | Bash | `git commit` 前に staged 差分の秘密情報パターンをスキャンしブロック | exit 2 |
| 7 | PreToolUse | Bash | `git commit` を `harness-log.jsonl` に記録 | しない |
| 8 | PreToolUse | Agent\|Task | サブエージェント起動（`subagent_type`）を `harness-log.jsonl` に記録 | しない |
| 9 | PreToolUse | Write\|Edit | 機密ファイル（`.env*`、credential / secret / `.pem` / `.key`）の編集をブロック | exit 2 |
| 10 | PreToolUse | Write\|Edit | Linter / Formatter / 型チェッカー設定ファイルの編集をブロック | exit 2 |

v2 での扱い（01 §4、D11）: 個別 Shell を廃止し `seh hook <event>` に集約する。#4 の単語一致フィードバック検出は廃止。#1〜#3 は SessionStart の警告整理と JSONL trace（`.harness/artifacts/`）へ置換。#5・#6・#9・#10 は `seh hook` の PreToolUse 検査として引き継ぎ、`seh` 導入済みで異常入力なら exit 2（fail-closed）。#7・#8 は trace へ統合。

## 4. 重複機能の指摘

| 重複・過剰 | 根拠 | v2 での解消 |
| --- | --- | --- |
| `test-writer` と `implementer` | `implementer` が TDD（Red→Green→Refactor）でテストを書く。`test-writer` は後付けテスト生成のみで、`implementer.md` の責務境界表に並置されている | `implementer` に統合（01 §3） |
| `refactorer` と `implementer` | `implementer` の Refactor 工程と通常リファクタリングが重なる | `implementer` に統合 |
| `design-reviewer` と `reviewer` | 観点（設計 / コード / セキュリティ）が違うだけで読み取り専用レビューという役割は同じ | `reviewer(review_type=design)` |
| `ci-triage` と `fixer` | CI ログ分類は決定論処理で足り、難問だけ `fixer` が扱えばよい | 決定論的な CI ログ分類器 + `fixer` |
| `researcher` と Claude Code 標準 Explore / Plan | 調査専用 Agent は標準機能と重複 | 基本構成から削除 |
| `self-review` / `address-review` / `create-pr` と `reviewer` / `gh` | レビュー・PR 操作を Skill の手順書で重ねている | ワークフローノードと `gh` アダプターに置換 |
| `brainstorm` の `parallel-dispatch.md` と `workflow.md` | 並列ディスパッチ手順が `workflow.md` と `brainstorm/references/` の両方にあり、`workflow.md` が後者を参照する | `/work` とワークフローエンジンに一本化 |
| `desloppify` | 外部ツール `desloppify` が `update-skill` で生成するベンダー Skill。`harness-init` が導入し `self-review` が呼ぶ。設計書に無い | DELETE（D9）。`.gitignore` の `.desloppify/` 行も削除 |
| `doctor` スキルと settings.json のプローブ（#2） | 健全性検査が Skill と SessionStart Hook に分散 | `seh doctor` に統合 |
| `CLAUDE.md` と `AGENTS.md` | どちらも rules への参照を持ち、ホストによっては二重に常時ロードされる（相互参照表で `coding` `workflow` `debugging` の参照元に両方が現れる） | 管理ブロックのみの短い生成物にする（05 設計書） |
| `memory.md` / `save-session` / `create-pr` | 記憶の保存タイミングが Rule と Skill で相互に参照し合っている（`memory.md` が `/create-pr` 実行後の保存を規定し、`save-session` は `memory.md` を参照） | `MemoryProvider` と evolution エンジンへ集約（機能自体は維持） |
| `.claude/_reference.md` と README | 設計思想の説明がどちらにもある | `docs/architecture.md` に統合 |

## 5. 移行時の注意

- D12: 移行対象の判定は本一覧（= `v1_known_paths.json`）。現物の sha256 が JSON と一致すれば計画どおり REWRITE / DELETE / MOVE、不一致なら `USER_OWNED_CONFLICT`、一覧外のパスは `KEEP`（ユーザー所有）。
- 作業ツリーの `CLAUDE.md` は 988a019 から変更済みなので、移行時は `USER_OWNED_CONFLICT` になる見込み。
- `.agents/`（未追跡、`skills → ../.claude/skills` のシンボリックリンク）は本一覧の対象外で、P8 の dogfooding で承認付きに置換する（D9）。
