# self-evolve-harness v2.0 Skill・Prompt作成／改善標準（必須ポリシー）

- 文書ID: SEH2-AUTHOR-001
- バージョン: 1.1（設計提案・未実装）
- 作成・更新日: 2026-11-04
- バージョン: 1.3（CLI First対応・設計提案）
- 適用先: 全4ホストの`SKILL.md`、Agent instructions、`CLAUDE.md`、`AGENTS.md`、`.claude/rules`、`.agents/rules`、`.opencode/agents`、Host hooks/plugins、Workflow Prompt、システム／開発者プロンプトのテンプレート、実行時生成プロンプト
- 関連: `01_改修方針書.md` / `02_要件定義書.md` / `03_実装計画書.md`

## 0. 規範

**Skill・プロンプトの作成・修正・自動生成は、動画の「コードベースQ&A→計画→コンテキスト管理→既存ツール接続→フィードバックによる反復」を原則とし、前回動画の「Eval First→比較実験→独立検証→昇格」を合格判定として追加する。**

最新の動画（アップロードファイル: `AnatoliKopadze-2117635023092211803-video-480x270.mp4`、約27分17秒）は、Boris Chernyによる**Claude Codeを使うための実践講演**であり、Skill生成アルゴリズムそのものを提示する動画ではない。以下は講演に現れる実践原則を**Skill/Promptの変更運用へ適用した設計**である。動画にない自動採点・CIゲート等はハーネス独自の追加要件として明記する。

動画から引き継ぐ実践: コードベースのQ&Aを先に行う、大規模変更の前に計画・承認を得る、CLI/MCPツールを再利用する、unit tests/ブラウザ/シミュレーターによるフィードバック、短い共有`CLAUDE.md`と必要に応じたスコープ別コンテキスト、複数セッションでのworktree分離、CLIの非対話JSON/JSONL出力。**個々のコマンド／ショートカットはClaude Codeの最新ドキュメントに従う**。

## 1. 適用範囲と作成しない判断

| 対象 | 適用 | 新規Skillを作るか |
|---|---|---|
| ユーザーの単発質問／単発指示 | 正確なContext + 目的 + 検証条件。短いタスクは直実行可 | 原則No |
| 繰り返し出てくる手順 | Explore→Plan→Skill構造→Eval→Promote | 再利用価値と既存重複を検査してYes |
| 決定論的な計算・ポリシー検証・ファイル操作 | Tool/スクリプトとして実装、schema付きで呼び出す | No |
| 常に必要なチーム規約 | 短い`CLAUDE.md`/path-scoped Rules、違反はHook/CI | No |
| 独立コンテキストや権限境界が必要な仕事 | 既存Subagentの再利用を優先 | 必要ならAgent、Skillとは別判断 |
| 非自明な条件分岐／再試行／並列 | Workflow RuntimeのGraphへ | Skillの長文指示で代替しない |

Skillの追加条件: (a)既存Skillや標準機能で実現できない、(b)反復利用する、(c)明確な起動条件と入出力、(d)対象Evalと停止条件が定義可能。**これを満たさない新規Skillは`NOT_NEEDED`として拒否またはTool/Promptに再配置**する。原則、公開Skillは`/harness-init`と`/work`の2つのままとする。作成専用の第3Skillは増やさず、`seh author ...`を内部機能として提供する。

## 2. 必須フロー（Authoring Lifecycle）

```text
TASK: create/update skill or prompt
    ↓
[0] CLASSIFY  目的 / 種別 / 影響範囲 / リスク
    ↓
[1] EXPLORE   read-only：関連コード・既存Skill・規約・Git履歴・CLI/MCP
    ↓
[2] DECIDE    Skill? Prompt? CLAUDE.md? Rule? Tool? Subagent? Runtime?
    ↓
[3] SPEC      期待動作、入力、出力、発火条件、禁止条件、検証手段
    ↓
[4] PLAN      変更差分と影響。高リスク/広域変更は人間の承認待ち
    ↓
[5] EVAL FIRST: baseline + positive/negative/edge/security regression cases
    ↓
[6] IMPLEMENT: 変更を小さく、prompt/data/code/runtimeを混ぜない
    ↓
[7] VERIFY    static lint + isolated fresh sessions + feedback tools
    ↓                 ↑
[8] REPAIR    evidenceに基づき対象のみ再作成（最大3回）
    ↓
[9] COMPARE   baseline vs candidate; no-skill vs skill（該当時）
    ↓
[10] PROMOTE  Gate+人間承認（条件により）+hash版管理+rollback
```

### 2.1 Explore（最初にコードを編集しない）

- プロジェクトルート、現行Skill/Agent/Rule/Hook、`CLAUDE.md`、MCP、ツール配置、参照箇所、Git履歴を確認する。
- 既存の繰り返し失敗や具体的な利用シナリオを探索する。**証拠のない「新しいSkillが必要」は採用しない**。
- 複数候補がある場合、まず既存ツールの`--help`/公式ドキュメント/既存MCPを調べ、同等のものを再実装しない。
- Explore phaseのモデルツール権限はread-only（情報取得のみ）。決定論的なリポジトリ探索結果を`AuthoringRecord`に記録する。

### 2.2 Plan とプロンプトの入力品質

Prompt/Skill本文の生成前に、少なくとも以下の情報を固定する。

1. **Goal**: 何を達成するか（曖昧な「良くする」は不可）。
2. **Inputs / Context**: 引数・参照元・必要ファイル・有効なツール。
3. **Boundaries**: 編集対象・実行権限・守る制約・やらないこと。
4. **Output Contract**: 返すものの形式／利用者／必須フィールド。
5. **Feedback**: 何を実行して成功と判断するか（テスト、lint、スクリーンショット等）。
6. **Trigger / Non-trigger**（Skillのみ）: 呼び出す条件・呼び出さない条件。

**大規模変更・共有ルール・セキュリティ権限を変える変更は、必ず計画を提示して承認後に実装**。表記修正や説明の変更には毎回承認を要求しないがCI静的検査は省かない。

### 2.3 Context Placement（肥大化防止）

| 書く場所 | 書く内容 | 書かない内容 |
|---|---|---|
| root `CLAUDE.md` | 常時必要な短い制約、Build/Testコマンド、主要参照リンク | 長い手順全文、滅多に使わない資料 |
| nested `CLAUDE.md` / `.claude/rules/` | 特定ディレクトリ／言語固有の制約 | プロジェクト全体の重複説明 |
| `SKILL.md` | 発動条件、1回の業務の主要手順、必要な参照へのリンク | 巨大な設計書、反復の状態管理 |
| `references/` / `.harness/knowledge/` | 必要なときだけ読む詳細資料・ドメイン知識 | 何でも常時読み込ませる設定 |
| `Tool Registry` | 計算・Git差分・ファイル操作・テストなど再現可能な処理 | 曖昧な自然言語での擬似的な正当性判断 |
| `Runtime/Policy` | ループ、時間予算、並列、許可/拒否、昇格基準 | 説明だけの「必ず〜する」 |

`CLAUDE.md`は短さを優先し、200行未満を推奨目安とする（**行数だけで合否を決めない**）。Skillはメタデータを短く明確にし、本文を用途に応じて遅延ロードする。現在のClaude Codeは`.claude/commands/`を引き続き受け入れるが、v2.0の新規設計では**Skillに寄せて重複を作らない**。

### 2.4 Skill Authoring Contract

- 有効なfrontmatter（`name`, `description`等、Hostがサポートするキーのみ）。Skill名は衝突・既存コマンド上書きを検査。
- descriptionには対象となるユーザー意図、発動例、境界を簡潔に含める。曖昧な「万能」「何でも」が自動起動するSkillは禁止。
- `allowed-tools`は必要最小限。GitHub CLI等の外部操作、シークレット、Bashの広域許可を不用意に付けない。
- 1つのSkillの目的は1つ。独立した用途・権限・評価セットが異なる場合のみ別モジュールに分離。
- エッジ条件・エラー対応・停止条件は明記する。コードを編集するSkillは**成功した証拠（テスト出力等）なしに「完了」と報告しない**。
- カスタムAgentやHost特有のキーはAdapterで生成し、他Hostにそのままコピーして「同等」と主張しない。
- Promptは役割/対象/必要な入力/制約/出力/評価手段だけを明確にし、冗長な掛け声や不要な内部推論出力要求を入れない。

## 3. 動画のフィードバック・ループをSkillとPromptに適用

| 対象 | 具体的なフィードバックツール | 合格例 |
|---|---|---|
| Skillの発火条件 | 新規セッションでpositive / negative promptを投入 | 対象時に起動し非対象時に起動しない |
| Skillの実行結果 | Fixture + テストコマンド + 独立review | 必須要件が満たされEvidenceが残る |
| JSON出力Prompt | Schema validator + 内容制約checker | 正しい構造と意味制約を満たす |
| コード実装Prompt | unit/integration tests, lint, typecheck | テストが通りスコープ逸脱なし |
| UI指示 | screenshot + ビジュアル確認/E2E | 成果物と参照要件の差異が解消 |
| セキュリティ指示 | 注入耐性・拒否・権限境界のテスト | 外部指示で許可範囲を拡張しない |

**生成した本人の自己評価を唯一の採点基準にしない**。必須条件はdeterministic checker（終了コード、構造、ファイル差分、許可等）で採点。意味品質で自動採点不能な条件は独立したreviewerによる評価と人間承認に切り分け、LLM judgeのスコアだけでは昇格しない。

- Skillは「あるべきタイミングで呼ばれるか」と「呼ばれた後に正しく動作するか」を**別々に評価**する。
- Skill変更時はfresh sessionで **skill enabled / disabled** を比較。Prompt変更時は旧版 / 新版を同一ケースで比較。
- 代表ケースにはpositive, negative, edge, regression, hostile input, permissionsを含める。
- 重要な変更では複数試行し成功率・所要時間・トークン・ツール回数・人間承認回数を記録。
- 変更したケースだけを合格させない。以前のMustケースの回帰は昇格不可。
- **最大3回の局所Repair**。超過時は`NEEDS_HUMAN`/`FAILED`に遷移し無限に書き換えない。
- Eval不可（モデル認証欠如、必要な外部ツール不在など）は`BLOCKED_NO_EVAL`。**PASSと偽らない**。

## 4. リスク別のゲート

| 変更カテゴリ | 静的lint | fresh-session実行Eval | 比較実験 | 事前人間承認 |
|---|---|---|---|---|
| 文言・typoのみ（動作変更なし） | 必須 | 原則省略可（変更検知） | 不要 | 不要 |
| Skillのdescription/triggerやPromptの動作変更 | 必須 | positive/negativeを必須 | baselineとの比較必須 | 影響範囲による |
| 共有`CLAUDE.md`、Agent権限、Tool許可、Hooks変更 | 必須 | 権限・安全性・回帰を必須 | baseline比較必須 | **必須** |
| 自動進化で生成されたPrompt/Skill | 必須 | ケース＋holdout＋回帰 | 必須 | 原則必須（安全境界は自動変更不可） |

変更種別は**変更対象パス、AST/frontmatter差分、権限/Hook差分**で保守的に分類。LLMが「軽微」と言っても権限設定が変わったら高リスク扱い。

## 5. 実装する強制機構：`authoring_guard`（新しいSkillは増やさない）

```text
Claude Code /work ─┐
                   ├─→ seh author plan ─→ AuthoringRecord
self-evolve engine ─┘           ↓
                         seh author lint
                                ↓
                        seh author eval
                                ↓
                        seh author compare
                                ↓
                        seh author promote
                                ↓
                             CI Gate
```

`src/seh/authoring/`を新設し、`classify.py`（編集対象・危険度）、`inventory.py`（既存機能の重複）、`spec.py`（契約）、`lint.py`、`eval.py`、`gate.py`、`promote.py`に責務を分割する。**公開Skillは増えない**。既存の`evals/`と`evolution/`を再利用するため、独立した重複Runnerや新しいEvolverは作らない。

### 5.1 Native Modeでの実装

1. `/work`の入口で対象がSkill/Prompt/Rule/Agent変更か検出。該当時`seh author plan`の結果を先に提示。
2. CLAUDE.mdに**数行の常時ルール**: "Prompt/Skillの変更は`seh author`経由、重要変更は計画承認、Eval結果なしの完了宣言禁止"。
3. Claude Codeの`PreToolUse` Hookは`Write`/`Edit`等で対象パスを検査し、保護対象に未承認の変更を試みたら拒否・差し戻す。ただし、Bashや外部エディタなど**すべての経路をPreToolUseだけでは遮断できない**。
4. `Stop`/タスク完了ゲートは変更差分とEvidenceを照合し、未評価なら`NEEDS_EVAL`とする。Stop Hookには無限ブロックをさせず制限回数後は状態で管理する。
5. **必須のCIチェック**はGit差分でSkill/Prompt変更を検出し、AuthoringRecord・lint・Eval evidence・承認を検証。Git push、GitHub PR、外部エディタ経由の変更にも対応。

### 5.2 Managed Runtimeでの実装

- `authoring-change` task typeに自動振り分け。`EXPLORE→PLAN→BASELINE→WRITE→VERIFY→COMPARE→PROMOTE`の状態機械をコードで強制。
- `PLAN`と`APPROVE`は別の状態。承認なしの状態遷移を拒否。
- Git worktreeで候補を隔離し、Spec/テスト/プロンプトのハッシュを固定。候補を検証するモデルセッションは新規に作る。
- 観測・評価のログは機密をマスクしたEvidence Bundleに記録。
- 承認済みであっても安全性ゲートに違反した変更を昇格させない。

**限界**: ネイティブClaude Codeの外部にあるファイル編集をリアルタイムに必ず防げるわけではない。**GitHub側の必須CIチェック／branch protection**を最終強制点とする。個人利用でCIがない場合は、完了時に`NOT_ENFORCED`と表示し保証を主張しない。

## 6. 実行用契約・成果物スキーマ

### 6.1 AuthoringRecord（概念例）

```json
{
  "id": "AUTH-20261104-001",
  "target_kind": "skill",
  "target_paths": [".claude/skills/work/SKILL.md"],
  "risk": "behavioral",
  "exploration": {
    "related_existing_modules": ["work", "harness-init"],
    "reuse_decision": "modify_existing",
    "evidence_refs": ["git:<commit>", "file:.claude/skills/work/SKILL.md"]
  },
  "spec": {
    "goal": "開発依頼に対して適切な検証が起動する",
    "trigger_examples": ["バグを修正して"],
    "non_trigger_examples": ["今の天気は？"],
    "output_contract": "evidence-backed result",
    "verification_tools": ["seh eval run"]
  },
  "plan_ref": "plans/AUTH-20261104-001.json",
  "approval_ref": null,
  "baseline_run_id": "eval:<baseline>",
  "candidate_run_id": "eval:<candidate>",
  "state": "AWAITING_EVAL"
}
```

RuntimeはJSON Schemaと許可遷移で各フィールドを検査。`approval_ref`がnullのまま高リスク変更をPROMOTEDにしない。`evidence_refs`は実際のパス・commit・digestが存在することを検証。

### 6.2 最低限のEval Suite

`tests/fixtures/prompt_skill/`に少なくとも次を置く。

- **TRIGGER+**: 明らかにSkillが必要な依頼
- **TRIGGER-**: 同じ語を含むがSkillが不要な依頼
- **BOUNDARY**: 曖昧な依頼・別のSkillとの重複
- **OUTPUT**: 正しいSchemaと実際の成果物
- **TOOL**: 既存CLI/MCPを正しく呼び、暗算/推測でごまかさない
- **REGRESSION**: 以前動いていた代表依頼
- **SECURITY**: 外部ファイルの指示注入、権限昇格の誘導
- **CONTEXT**: 不要な長大context注入がない

起動テストは必ず**空の新規セッション**。不要Skillを読み込ませた過去の会話履歴で新Skillを評価しない。インストール可能なPlugin形式ならClaude Code公式のPlugin Evalの再利用を第一候補とし、汎用プロンプトは既存`seh eval` runnerへ統合する。

### 6.3 昇格判定の不変条件（Must）

```text
promote(candidate) =
  schema_ok
  AND no_permission_escalation
  AND all_must_regressions_pass
  AND behavioral_change_has_fresh_eval
  AND baseline_comparison_exists
  AND (risk_not_high OR human_approval_exists)
  AND evidence_hashes_match(candidate)
  AND ownership_policy_passes
```

統計的成功率の改善は評価材料であり、危険な変更を上書きする条件にならない。候補が不採用でも元のSkill/Promptは使用し続けられる。

## 7. `seh author` CLI（提案）

```bash
seh author inspect --path .claude/skills/work/SKILL.md
seh author plan --target .claude/skills/work/SKILL.md
seh author lint --changed --format json
seh author eval --record .harness/authoring/AUTH-20261104-001.json --fresh
seh author compare --baseline <run-id> --candidate <run-id>
seh author promote --record .harness/authoring/AUTH-20261104-001.json --approval <approval-id>
seh author rollback --promotion <promotion-id>
```

`seh author`は実装予定のCLIで、現行リポジトリに存在しない。`--changed`はGit diffの変更パスから必要な検査だけを決め、存在しないケースのPASSは認めない。

## 8. 品質目標・DoD

- [ ] 同じ作業に対しSkill増設なしで既存Skill/CLI/MCPを優先できる
- [ ] 新しいPrompt/Skillの作成前に探索ログ・設計判断・成功条件・評価手段が記録される
- [ ] 既存Skillとの命名衝突・重複発火のテストが通る
- [ ] 必須のSkill positive/negative trigger評価と、作動後のoutcome評価が**別々に**PASS
- [ ] 動作変更時はbaseline/candidateを**fresh session**で比較し、Must回帰ゼロ
- [ ] 機密/権限/Hook変更は明示的承認なしで適用されない
- [ ] ループは最大3回に制限され、FAILをPASSに書き換えない
- [ ] `native`でHookをすり抜ける編集でも、必須CIがブロックする
- [ ] `CLAUDE.md`とSkillに同じ長文手順が複写されていない
- [ ] `authoring_guard`は既存Eval/Runtimeを再利用し**新たな公開Skill/Agentを追加しない**
- [ ] ビルド・テスト・UI確認等、Domainに合ったフィードバックツールが登録されている
- [ ] 評価環境が使えない場合は`BLOCKED_NO_EVAL`を返し、未検証のまま合格扱いしない

## 9. 出典・確認範囲

**追加動画（今回）**: `AnatoliKopadze-2117635023092211803-video-480x270.mp4`（27分17秒、画面を確認）。併せて以下の講演文字起こしを参照。ただし文字起こしは二次資料・自動生成であり、現行仕様の正本ではない。

- 講演の文字起こし: https://claytonsmith.ca/pages/anatoli-kopadze-practical-claude-code-tips-and-tricks.html
- Claude Code公式・Skills: https://code.claude.com/docs/en/skills
- Claude Code公式・Memory: https://code.claude.com/docs/en/memory
- Claude Code公式・Hooks: https://code.claude.com/docs/en/hooks
- Claude Code公式・Best practices: https://code.claude.com/docs/en/best-practices
- 前回動画（Eval First）: `huxlab-2115621902958170125-video-1280x720.mp4`


## 10. v1.2：Claude以外のホストにも同一基準を適用

`CLAUDE.md`を**実行規則の唯一の正本にしない**。正本`.harness/spec/`をHostAdapterで`CLAUDE.md`、`AGENTS.md`、`.agents/rules/`、各HostのSkill/Agent/Hook/Pluginへ生成する。`seh author`はすべての生成先と正本の変更を検出する。

- **Google Antigravity (AGY)**: `.agents/skills/`、`.agents/rules/`、`.agents/hooks.json`（実際のsurfaceに応じた対応可否を診断）。
- **Codex**: `AGENTS.md`、`.agents/skills/`、Codex標準設定と`codex exec`。Hook相当が不十分な箇所はCI強制。
- **OpenCode**: `AGENTS.md`、`.agents/skills/`、`.opencode/agents/`、`.opencode/plugins/`。Claudeとの同時配置は重複Discoveryを検証。
- **Claude Code**: `CLAUDE.md`、`.claude/skills/`、`.claude/agents/`、`.claude/settings.json`。

すべて同じAuthoringRecord/Fixture/Evidence/Promotion Policyを利用し、Host別fresh sessionでTriggerとOutcomeを計測する。Hostが持たない機能は`CI_ONLY`、`UNSUPPORTED`、`UNVERIFIED`とし、ClaudeでPASSした結果を他Hostへコピーして合格扱いしない。詳細は`05_マルチホスト互換性・実行設計.md`。

## 11. v1.3: CLI Firstを著作・評価プロセスへ適用

- 新しいSkill・Promptを作成するためにSDK依存や「作成専用Skill」を増やさない。既存の`/work`／`seh author`と公式CLIでExplore・Baseline・Evaluationを行う。
- `seh author eval`は`CliAgentRunner`でホスト別fresh sessionを起動し、`SKILL.md`が**発火したか**と実際の成果物が**正しいか**を別々に採点する。
- 公式CLIが構造化出力の直接制約に対応しなくてもHarness側でSchema検証し、失敗は`INVALID_OUTPUT`として限定回数だけ修正。
- Codex/OpenCode/Claudeの結果をAGYで代用しない。AGYの利用条件でManaged起動が不可なら`POLICY_BLOCKED`とし、AGYの成果品質が評価済みだと表示しない。手動/ネイティブ操作の検証は別区分に記録する。
- CIは生成された各ホストの設定と共通Policy/Evalを検査する。CLIが利用不能なCIではMock合同テストのみをPASSとし、実ホストE2Eは`NOT_RUN`のまま残す。
- `prompting`の改善方式は動画に従うが、SDKは必須ではない。**決定論的評価結果と回帰検出が採用条件**。

参照: `06_CLIランナー・SDK任意化設計.md`。
