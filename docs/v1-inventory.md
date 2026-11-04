# v1 資産棚卸し

- 基準: コミット `4c5ac19`（v1 最終コミット。origin/main 上。P0 で `v1-baseline` タグを打つ）
- 目的: v1 の全資産と参照関係を把握し、移行（T22）と参照監査（T24）の入力にする。機械可読な正本は `src/seh/migration/v1_known_paths.json`（各ファイルの sha256 と `v2_action` を持つ）。
- 根拠: `docs/design/v2/01_改修方針書.md` §2〜4、`docs/specs/2026-11-04-v2-harness-requirements.md` D3 / D9 / D12 / D14。
- 本ファイルは参照監査の除外パス（D14）なので、旧 Skill / Agent / Rule 名が現れてよい。
- 前回の棚卸しは 988a019 基準だった。リモートに未取得の v1 コミット 3 件（6eb2c79 / b08c37e / 4c5ac19）があったため 4c5ac19 基準で作り直した（差分は §5）。

## 1. ファイル一覧（56 件）

対象は 4c5ac19 で git 追跡されている `.claude/**`、`CLAUDE.md`、`AGENTS.md`、`.github/pull_request_template.md`、`.agent-memory/**`。`.claude/settings.local.json`、`.claude/harness-log.jsonl`、`.claude/worktrees/` は追跡外（`.claude/.gitignore` で除外）なので含めない。

種別: skill / agent / rule / hook_config（settings.json）/ instructions（CLAUDE.md, AGENTS.md）/ reference（参照資料）/ template / script / memory（`.agent-memory/**`）/ other。

| パス | 種別 | v2 での扱い |
| --- | --- | --- |
| `.agent-memory/MEMORY.md` | memory | KEEP |
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
| `.claude/scripts/doctor.sh` | script | DELETE |
| `.claude/settings.json` | hook_config | REWRITE |
| `.claude/skills/address-review/SKILL.md` | skill | DELETE |
| `.claude/skills/brainstorm/SKILL.md` | skill | DELETE |
| `.claude/skills/brainstorm/references/parallel-dispatch.md` | reference | DELETE |
| `.claude/skills/create-pr/SKILL.md` | skill | DELETE |
| `.claude/skills/create-skill/SKILL.md` | skill | DELETE |
| `.claude/skills/desloppify/SKILL.md` | skill | DELETE |
| `.claude/skills/evolve-rules/SKILL.md` | skill | DELETE |
| `.claude/skills/evolve-rules/references/ahe-principles.md` | reference | MOVE |
| `.claude/skills/harness-init/SKILL.md` | skill | REWRITE |
| `.claude/skills/harness-init/languages/_generic.md` | reference | MOVE |
| `.claude/skills/harness-init/languages/c-cpp.md` | reference | MOVE |
| `.claude/skills/harness-init/languages/csharp.md` | reference | MOVE |
| `.claude/skills/harness-init/languages/go.md` | reference | MOVE |
| `.claude/skills/harness-init/languages/java.md` | reference | MOVE |
| `.claude/skills/harness-init/languages/node.md` | reference | MOVE |
| `.claude/skills/harness-init/languages/python.md` | reference | MOVE |
| `.claude/skills/harness-init/languages/rust.md` | reference | MOVE |
| `.claude/skills/harness-init/languages/terraform.md` | reference | MOVE |
| `.claude/skills/harness-init/memory-backends/common.md` | reference | MOVE |
| `.claude/skills/harness-init/memory-backends/engram.md` | reference | MOVE |
| `.claude/skills/harness-init/memory-backends/file.md` | reference | MOVE |
| `.claude/skills/harness-init/shared/hooks-boilerplate.md` | reference | MOVE |
| `.claude/skills/harness-init/shared/rules-skeleton.md` | reference | MOVE |
| `.claude/skills/harness-init/task-runners/_generic.md` | reference | MOVE |
| `.claude/skills/harness-init/task-runners/cargo.md` | reference | MOVE |
| `.claude/skills/harness-init/task-runners/just.md` | reference | MOVE |
| `.claude/skills/harness-init/task-runners/make.md` | reference | MOVE |
| `.claude/skills/harness-init/task-runners/moon.md` | reference | MOVE |
| `.claude/skills/harness-init/task-runners/npm-scripts.md` | reference | MOVE |
| `.claude/skills/harness-sync/SKILL.md` | skill | DELETE |
| `.claude/skills/save-session/SKILL.md` | skill | DELETE |
| `.claude/skills/self-review/SKILL.md` | skill | DELETE |
| `.github/pull_request_template.md` | template | KEEP |
| `AGENTS.md` | instructions | REWRITE |
| `CLAUDE.md` | instructions | REWRITE |

集計: KEEP 2 / REWRITE 12 / MOVE 23 / DELETE 19 (合計 56)

v2_action の意味:

- KEEP: v2 でも内容を維持する。
- REWRITE: 同じパスまたは同じ役割で v2 の内容に書き換える（生成物化を含む）。
- MOVE: 内容の知見を別の場所（`.harness/knowledge/`、`seh` のコード、`docs/`）へ移し、元のファイルは残さない。
- DELETE: 機能を `seh` / 他の Agent へ統合し、ファイルを削除する。

分類の根拠:

- Skill: 公開は `/harness-init`（REWRITE）と `/work`（新規）の 2 種（01 §2）。他は DELETE。`desloppify` は設計書に無いローカル資産で D9 により DELETE。`harness-sync` は `seh sync --hosts` に置換して DELETE（D9）。
- `.claude/scripts/doctor.sh`: `seh doctor` に置換して DELETE（D9。v1 最終版では `doctor` スキルが削除され、このスクリプトに置き換わっている）。
- `harness-init` 配下の `languages/`（`c-cpp.md` `csharp.md` を含む）`task-runners/` `shared/` は、検出ロジックを `seh init`（T15）へコード化するため MOVE。`memory-backends/`（`common.md` `engram.md` `file.md`）は知見を `providers/memory/` へ移して MOVE（D9）。`evolve-rules/references/ahe-principles.md` は evolution エンジンの知見として MOVE。`brainstorm/references/parallel-dispatch.md` は `/work` とワークフローエンジンに置き換わるため DELETE。
- Agent: `implementer` `reviewer` `fixer` `evolver` を維持（REWRITE）、他 5 件は DELETE（01 §3）。
- Rule: `coding` は `engineering.md` へ統合、`testing` は簡潔化、`architecture` は条件付き生成（いずれも REWRITE）。`domain` は `.harness/knowledge/domain.md` へ MOVE。`debugging` `workflow` `memory` は DELETE（01 §4。`memory` の選択式バックエンド知見は MemoryProvider へ移る）。
- `.claude/settings.json` は個別 Shell Hook を `seh hook <event>` に集約する薄いシムへ REWRITE。`CLAUDE.md` / `AGENTS.md` は管理ブロックのみ更新する REWRITE。`.claude/.gitignore` は D14a により REWRITE。
- `.claude/_reference.md` は `docs/architecture.md` へ統合（MOVE。要件 D 節の P8 記述）。
- `.github/pull_request_template.md` は残す（KEEP）。
- `.agent-memory/**`（`MEMORY.md`）は v1 の file 記憶バックエンドのユーザーデータ。KEEP（D9）。v2 の `memory.provider = "file"` は既定の保存先をここにし、v1 の記憶形式を読み書きできること（FR-040）。

## 2. 相互参照表

各 Skill / Agent / Rule の名前が、どのファイルから参照されているか。

- 手順: 4c5ac19 の全追跡ファイル（`git ls-tree -r --name-only 4c5ac19` のうち `docs/` を除く）の blob に対する名前一致（`git grep <name> 4c5ac19` 相当）。Skill は `/<name>` または `` `<name>` ``、Agent は単語境界つきの名前、Rule は `<name>.md` または `[[<name>]]`。自分自身と `docs/` 配下は除く。
- 近似: 一般語と重なる名前（`fixer` `reviewer` `memory` `doctor` など）は文脈の異なる言及を含みうる。実参照の確定は T24 の監査実装で行う。
- `README.md` は棚卸し対象（`.claude/**` 等）外だが、参照元として列挙する。v2 で README の更新が必要（要件の完了条件）。
- 4c5ac19 で削除された `doctor` スキルは一覧（§1）にない。そのため `doctor` の表は含めない。

### Skill

| 名前 | v2 | 参照元 |
| --- | --- | --- |
| `address-review` | DELETE | `.claude/_reference.md`<br>`README.md` |
| `brainstorm` | DELETE | `.claude/_reference.md`<br>`.claude/rules/workflow.md`<br>`.claude/skills/harness-sync/SKILL.md`<br>`.claude/skills/self-review/SKILL.md`<br>`AGENTS.md`<br>`CLAUDE.md`<br>`README.md` |
| `create-pr` | DELETE | `.claude/_reference.md`<br>`.claude/rules/memory.md`<br>`.claude/skills/address-review/SKILL.md`<br>`.claude/skills/brainstorm/SKILL.md`<br>`.claude/skills/harness-init/memory-backends/common.md`<br>`.claude/skills/save-session/SKILL.md`<br>`README.md` |
| `create-skill` | DELETE | `.claude/_reference.md`<br>`.claude/skills/evolve-rules/SKILL.md`<br>`README.md` |
| `desloppify` | DELETE | `.claude/skills/harness-init/SKILL.md`<br>`.claude/skills/self-review/SKILL.md` |
| `evolve-rules` | DELETE | `.claude/_reference.md`<br>`.claude/agents/evolver.md`<br>`.claude/rules/memory.md`<br>`.claude/skills/harness-init/memory-backends/common.md`<br>`CLAUDE.md`<br>`README.md` |
| `harness-init` | REWRITE | `.claude/_reference.md`<br>`.claude/agents/evolver.md`<br>`.claude/rules/architecture.md`<br>`.claude/rules/coding.md`<br>`.claude/rules/domain.md`<br>`.claude/rules/memory.md`<br>`.claude/rules/testing.md`<br>`.claude/rules/workflow.md`<br>`.claude/scripts/doctor.sh`<br>`.claude/skills/evolve-rules/SKILL.md`<br>`.claude/skills/harness-init/languages/_generic.md`<br>`.claude/skills/harness-init/languages/c-cpp.md`<br>`.claude/skills/harness-init/languages/csharp.md`<br>`.claude/skills/harness-init/languages/node.md`<br>`.claude/skills/harness-init/languages/python.md`<br>`.claude/skills/harness-init/memory-backends/common.md`<br>`.claude/skills/harness-init/shared/hooks-boilerplate.md`<br>`.claude/skills/harness-init/shared/rules-skeleton.md`<br>`.claude/skills/save-session/SKILL.md`<br>`CLAUDE.md`<br>`README.md` |
| `harness-sync` | DELETE | `.claude/_reference.md`<br>`.claude/rules/memory.md`<br>`.claude/scripts/doctor.sh`<br>`.claude/skills/harness-init/SKILL.md`<br>`.claude/skills/harness-init/memory-backends/engram.md`<br>`.claude/skills/harness-init/memory-backends/file.md`<br>`README.md` |
| `save-session` | DELETE | `.claude/_reference.md`<br>`.claude/rules/memory.md`<br>`.claude/skills/address-review/SKILL.md`<br>`.claude/skills/create-pr/SKILL.md`<br>`.claude/skills/harness-init/memory-backends/common.md`<br>`CLAUDE.md`<br>`README.md` |
| `self-review` | DELETE | `.claude/_reference.md`<br>`.claude/rules/workflow.md`<br>`.claude/skills/brainstorm/SKILL.md`<br>`README.md` |

### Agent

| 名前 | v2 | 参照元 |
| --- | --- | --- |
| `ci-triage` | DELETE | `.claude/_reference.md`<br>`.claude/skills/brainstorm/SKILL.md`<br>`.claude/skills/brainstorm/references/parallel-dispatch.md`<br>`AGENTS.md`<br>`README.md` |
| `design-reviewer` | DELETE | `.claude/_reference.md`<br>`.claude/skills/brainstorm/SKILL.md`<br>`README.md` |
| `evolver` | REWRITE | `.claude/_reference.md`<br>`.claude/rules/memory.md`<br>`.claude/settings.json`<br>`.claude/skills/evolve-rules/SKILL.md`<br>`.claude/skills/harness-init/SKILL.md`<br>`.claude/skills/harness-init/memory-backends/common.md`<br>`.claude/skills/harness-init/memory-backends/engram.md`<br>`.claude/skills/harness-init/shared/hooks-boilerplate.md`<br>`AGENTS.md`<br>`CLAUDE.md`<br>`README.md` |
| `fixer` | REWRITE | `.claude/_reference.md`<br>`.claude/agents/ci-triage.md`<br>`.claude/agents/implementer.md`<br>`.claude/rules/workflow.md`<br>`.claude/skills/brainstorm/SKILL.md`<br>`.claude/skills/brainstorm/references/parallel-dispatch.md`<br>`.claude/skills/desloppify/SKILL.md`<br>`.claude/skills/evolve-rules/SKILL.md`<br>`AGENTS.md`<br>`CLAUDE.md`<br>`README.md` |
| `implementer` | REWRITE | `.claude/_reference.md`<br>`.claude/rules/workflow.md`<br>`.claude/skills/brainstorm/SKILL.md`<br>`.claude/skills/brainstorm/references/parallel-dispatch.md`<br>`.claude/skills/evolve-rules/SKILL.md`<br>`CLAUDE.md`<br>`README.md` |
| `refactorer` | DELETE | `.claude/_reference.md`<br>`.claude/agents/ci-triage.md`<br>`.claude/agents/implementer.md`<br>`.claude/agents/reviewer.md`<br>`.claude/skills/brainstorm/SKILL.md`<br>`AGENTS.md`<br>`README.md` |
| `researcher` | DELETE | `.claude/_reference.md`<br>`.claude/skills/harness-init/languages/_generic.md`<br>`AGENTS.md`<br>`README.md` |
| `reviewer` | REWRITE | `.claude/_reference.md`<br>`.claude/agents/refactorer.md`<br>`.claude/rules/workflow.md`<br>`.claude/skills/brainstorm/SKILL.md`<br>`.claude/skills/desloppify/SKILL.md`<br>`.claude/skills/evolve-rules/SKILL.md`<br>`.claude/skills/self-review/SKILL.md`<br>`README.md` |
| `test-writer` | DELETE | `.claude/_reference.md`<br>`.claude/agents/implementer.md`<br>`.claude/rules/workflow.md`<br>`README.md` |

### Rule

| 名前 | v2 | 参照元 |
| --- | --- | --- |
| `architecture` | REWRITE | `.claude/_reference.md`<br>`.claude/agents/design-reviewer.md`<br>`.claude/agents/implementer.md`<br>`.claude/agents/reviewer.md`<br>`.claude/skills/brainstorm/references/parallel-dispatch.md`<br>`.claude/skills/harness-init/SKILL.md`<br>`.claude/skills/harness-init/shared/rules-skeleton.md`<br>`.claude/skills/self-review/SKILL.md`<br>`CLAUDE.md` |
| `coding` | REWRITE | `.claude/_reference.md`<br>`.claude/agents/ci-triage.md`<br>`.claude/agents/implementer.md`<br>`.claude/rules/testing.md`<br>`.claude/rules/workflow.md`<br>`.claude/skills/brainstorm/SKILL.md`<br>`.claude/skills/brainstorm/references/parallel-dispatch.md`<br>`.claude/skills/harness-init/SKILL.md`<br>`.claude/skills/harness-init/shared/rules-skeleton.md`<br>`AGENTS.md`<br>`CLAUDE.md` |
| `debugging` | DELETE | `.claude/_reference.md`<br>`.claude/skills/evolve-rules/SKILL.md`<br>`.claude/skills/harness-init/SKILL.md`<br>`.claude/skills/harness-init/shared/rules-skeleton.md`<br>`AGENTS.md`<br>`CLAUDE.md` |
| `domain` | MOVE | `.claude/_reference.md`<br>`.claude/skills/harness-init/SKILL.md`<br>`.claude/skills/harness-init/shared/rules-skeleton.md`<br>`CLAUDE.md` |
| `memory` | DELETE | `.agent-memory/MEMORY.md`<br>`.claude/_reference.md`<br>`.claude/agents/evolver.md`<br>`.claude/scripts/doctor.sh`<br>`.claude/settings.json`<br>`.claude/skills/evolve-rules/SKILL.md`<br>`.claude/skills/harness-init/SKILL.md`<br>`.claude/skills/harness-init/memory-backends/common.md`<br>`.claude/skills/harness-init/memory-backends/engram.md`<br>`.claude/skills/harness-init/memory-backends/file.md`<br>`.claude/skills/harness-init/shared/hooks-boilerplate.md`<br>`.claude/skills/harness-init/shared/rules-skeleton.md`<br>`.claude/skills/harness-sync/SKILL.md`<br>`.claude/skills/save-session/SKILL.md`<br>`CLAUDE.md` |
| `testing` | REWRITE | `.claude/_reference.md`<br>`.claude/agents/implementer.md`<br>`.claude/agents/reviewer.md`<br>`.claude/agents/test-writer.md`<br>`.claude/skills/brainstorm/references/parallel-dispatch.md`<br>`.claude/skills/harness-init/SKILL.md`<br>`.claude/skills/harness-init/shared/rules-skeleton.md`<br>`.claude/skills/self-review/SKILL.md`<br>`CLAUDE.md` |
| `workflow` | DELETE | `.claude/_reference.md`<br>`.claude/agents/ci-triage.md`<br>`.claude/agents/implementer.md`<br>`.claude/agents/researcher.md`<br>`.claude/skills/address-review/SKILL.md`<br>`.claude/skills/brainstorm/SKILL.md`<br>`.claude/skills/brainstorm/references/parallel-dispatch.md`<br>`.claude/skills/harness-init/SKILL.md`<br>`.claude/skills/harness-init/shared/rules-skeleton.md`<br>`.claude/skills/self-review/SKILL.md`<br>`AGENTS.md`<br>`CLAUDE.md`<br>`README.md` |

## 3. settings.json の Hook 一覧（13 件）

すべて `type: command` のインライン Shell。`settings.json` にはほかに `permissions` キーがある。

| # | イベント | matcher | 目的 | ブロック |
| --- | --- | --- | --- | --- |
| 1 | SessionStart | startup | `.agent-memory/*.md` の `evolve: pending` が 3 件以上なら AUTO-EVOLVE 通知 | しない |
| 2 | SessionStart | startup | 環境健全性プローブ（メモリ索引なし、codegraph 未検出、settings.local.json の JSON 不正を警告。`bash .claude/scripts/doctor.sh` を案内） | しない |
| 3 | SessionStart | startup | `session_start` を `.claude/harness-log.jsonl` に記録 | しない |
| 4 | SessionStart | startup | `.agent-memory/MEMORY.md` の先頭 200 行を Context に注入 | しない |
| 5 | SessionStart | startup | 索引が 20000B 超なら AUTO-ORGANIZE 通知（`memory.md` の整理手順を促す） | しない |
| 6 | UserPromptSubmit | （なし） | 発話の修正語（違う・直して 等）を単語一致で検出し、feedback メモリ保存を促す | しない |
| 7 | PreToolUse | Bash | 破壊的コマンド（ルート・ホームへの再帰削除、管理者権限昇格 等）をブロック | exit 2 |
| 8 | PreToolUse | Bash | `git commit` 前に staged 差分の秘密情報パターンをスキャンしブロック | exit 2 |
| 9 | PreToolUse | Bash | `git commit` を `harness-log.jsonl` に記録 | しない |
| 10 | PreToolUse | Agent\|Task | サブエージェント起動（`subagent_type`）を `harness-log.jsonl` に記録 | しない |
| 11 | PreToolUse | Write\|Edit | 機密ファイル（`.env*`、credential / secret / `.pem` / `.key`）の編集をブロック | exit 2 |
| 12 | PreToolUse | Write\|Edit | Linter / Formatter / 型チェッカー設定ファイルの編集をブロック | exit 2 |
| 13 | PreToolUse | Skill | Skill 呼び出し（`skill` 名）を `harness-log.jsonl` に記録 | しない |

## 4. 重複機能

v2 で 1 つに統合される、または互いに役割が重なっている v1 資産。

| 機能 | v1 での重複箇所 | v2 での統合先 |
| --- | --- | --- |
| 環境健全性チェック | settings.json の SessionStart #2、`.claude/scripts/doctor.sh` | `seh doctor` |
| ログ記録 | settings.json の #3 / #9 / #10 / #13（各 Hook が個別に `harness-log.jsonl` へ追記） | `seh hook <event>` の単一ログ書込み |
| 記憶（保存・検索・索引） | `rules/memory.md`（選択式バックエンド）、`harness-init/memory-backends/`、`save-session`、`evolve-rules`、SessionStart #1 / #4 / #5、UserPromptSubmit #6 | MemoryProvider（`providers/memory/`）と evolution エンジン |
| ホスト別生成物の同期 | `harness-sync`、`AGENTS.md`、`CLAUDE.md`、`harness-init` | `seh sync --hosts` |
| レビュー | `self-review`、`reviewer`、`design-reviewer`、`address-review` | `reviewer` Agent と `/work` のレビュー段 |
| 実装系の分業 | `implementer`、`test-writer`、`refactorer`、`fixer`、`ci-triage` | `implementer` / `fixer` に集約 |
| 並列実行・ワークフロー | `brainstorm`、`rules/workflow.md`、`brainstorm/references/parallel-dispatch.md` | `/work` とワークフローエンジン |
| 規約の二重管理 | `CLAUDE.md` の規約表と `rules/*.md`、`_reference.md` の一覧 | `.harness/` の正本から生成 |

## 5. 988a019 から 4c5ac19 への変更

`git diff --name-status 988a019 4c5ac19` による（対象は §1 のスコープ）。追跡ファイル数は 49 件から 56 件に増えた（追加 8 / 削除 1）。

追加（8 件）:

| パス | v2 での扱い |
| --- | --- |
| `.agent-memory/MEMORY.md` | KEEP |
| `.claude/scripts/doctor.sh` | DELETE（`seh doctor` に置換） |
| `.claude/skills/harness-sync/SKILL.md` | DELETE（`seh sync --hosts` に置換） |
| `.claude/skills/harness-init/languages/c-cpp.md` | MOVE |
| `.claude/skills/harness-init/languages/csharp.md` | MOVE |
| `.claude/skills/harness-init/memory-backends/common.md` | MOVE（`providers/memory/` へ） |
| `.claude/skills/harness-init/memory-backends/engram.md` | MOVE（同上） |
| `.claude/skills/harness-init/memory-backends/file.md` | MOVE（同上） |

削除（1 件）: `.claude/skills/doctor/SKILL.md`（`.claude/scripts/doctor.sh` に置き換え。Skill description の常時コストを削減する意図）。

内容変更: 上記以外の既存 `.claude/**`、`CLAUDE.md`、`AGENTS.md`、`.github/pull_request_template.md` が更新された（スコープ外の `README.md` も更新）。主な変化:

- 記憶層が Engram 一本化から「選択式バックエンド（file / engram）」に変わった。file の保存先は `.agent-memory/` で、`rules/memory.md` が `memory-backends/` から生成される。
- `settings.json` の Hook が 10 件から 13 件に増えた（SessionStart に索引注入と AUTO-ORGANIZE、PreToolUse に Skill 記録を追加）。SessionStart #1 / #2 / #3 と UserPromptSubmit の文言は Engram 前提から `.agent-memory/` 前提に変わった。
- `harness-sync` によるマルチツール共有（`AGENTS.md` 共通ブロック、OpenCode / Codex 向け生成）が加わった。
- `.claude/rules/memory.md` は 2637 文字から 5290 文字に増え、常時 Context が大きくなった（`docs/baseline/v1-context.md` 参照）。

### v2 要件への影響

D3（基準を 4c5ac19 に訂正）と D9（`harness-sync` / `doctor.sh` / `memory-backends/` は DELETE または MOVE、`.agent-memory/` は KEEP）は要件側で更新済み。
