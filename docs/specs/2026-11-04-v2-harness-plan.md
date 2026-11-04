# 実装計画: self-evolve-harness v2.0（P0〜P8・設計 v1.3 準拠）

- 前提: `docs/specs/2026-11-04-v2-harness-requirements.md`（承認済み、D1〜D18）、`docs/design/v2/`（v1.3）
- アプローチ: **契約先行 + フェーズ内 wave 並列**（ユーザー選択）

## アプローチ

1. **P0〜P1 で全契約を固定する**: TaskSpec / WorkUnit / Edge / Verdict / RunResult / TerminalState / CanonicalSpec / HostCapability / ModuleManifest / AuthoringRecord / Result と JSON Schema。以降のタスクは契約に依存し、互いのファイルには依存しない。
2. **設計 v1.3 のフェーズ順で進める**: Host render は P2 に前倒しする。P2 と P3、P4 と P6 は wave を重ねる。
3. **各 wave の条件**: 所有ファイルが互いに素なタスクで編成し、`implementer` を最大4並列で起動する。barrier で境界検証 → `CI_CHECK_CMD` → wave コミットを行う。
4. **共有ホットスポットは先に作る**: `cli.py`、`commands/__init__.py`、`pyproject.toml` は T01 が全サブコマンド分のスタブと全依存を先に作る。以降の各タスクは自分の `commands/<group>.py` だけを所有する。
5. **P8 の dogfooding apply は計画済み停止点**: W17 で apply 計画を提示して停止する（D13）。

### 依存パッケージ（T01 で一括宣言・以降追加しない方針）

- 実行時: `jsonschema`、`pyyaml`、`tomli-w`（TOML 読込は stdlib の `tomllib`）
- dev: `pytest`、`pytest-asyncio`、`ruff`、`pyright`
- SDK 系は入れない（FR-086）

### レイヤー（依存方向。上位は下位にだけ依存してよい）

```
cli.py → commands/*            （入出力・対話・承認取得のみ）
   ↓
init/ migration/ sync.py audit.py doctor/ authoring/ evals/ evolution/ runtime/managed.py
   ↓
runtime/(graph, scheduler, worktree, repair, checkpoint, runners/*) providers/(hosts, codeintel, memory) tools/
   ↓
config.py registry.py policy.py ownership.py events.py trace.py artifacts.py redaction.py runtime/process.py
   ↓
contracts/*  schemas/*          （stdlib と jsonschema 以外に依存しない）
```

禁止事項:
- `contracts/` から上位を import しない。
- `providers/hosts/*` は subprocess を起動しない（05 §2）。
- `evolution/` は `policy.py` に書き込まない。
- `runners/*` は Verdict を生成しない（判定は `evals/checker.py` と `runtime/gate.py` だけ）。

## タスク分割

凡例:
- テスト方針: U = 単体、I = 結合（一時 git repo / 一時 HOME / mock CLI）、E = E2E、R = 実 CLI（`real` marker、オーケストレータが上限内で実行）
- 所有ファイル: 各タスクのテストは `tests/unit/<area>/`、`tests/integration/<area>/` 配下の、そのタスク名のディレクトリを所有する（表では `tests/**/<area>/` と略記）

### P0: ベースラインと評価設計（W1）

| # | タスク | 所有ファイル | テスト方針 | wave | 依存 |
|---|---|---|---|---|---|
| T01 | プロジェクト骨格。pyproject（D2 の全設定）、`seh --help`、全サブコマンドのスタブ（`init doctor config module sync work eval author evolve migrate hook`）、CI ワークフロー、CLAUDE.md の CI コマンド確定、.gitignore（`.venv`、`__pycache__`） | `pyproject.toml`, `uv.lock`, `src/seh/__init__.py`, `src/seh/__main__.py`, `src/seh/cli.py`, `src/seh/commands/__init__.py`, `src/seh/commands/{init,doctor,config,module,sync,work,eval,author,evolve,migrate,hook}.py`（スタブ）, `tests/unit/cli/`, `.github/workflows/ci.yml`, `CLAUDE.md`（CI 節のみ）, `.gitignore` | U（`seh --help` と各スタブの終了コード） | 1 | なし |
| T02 | v1 棚卸し。全 Skill / Agent / Rule / Hook と相互参照、所有元、重複機能。常時 Context 量（NFR-011）と CLI 速度の測定方法を記録。v1 既知パス一覧のデータも作る | `docs/v1-inventory.md`, `docs/baseline/v1-context.md`, `src/seh/migration/v1_known_paths.json` | なし（文書・データ）。T22 がデータを検証する | 1 | なし |
| T03 | 決定記録（researcher が調査し、オーケストレータが記述）。4ホストの生成形式と CLI フラグ（`--help` 実測 + 公式資料）、OpenCode の Claude 互換パス無効化、Codex / AGY / OpenCode の Hook 手段、AGY の Subagent 形式、Graphify の正式リポジトリと CLI 契約 | `docs/decisions/0001-host-formats.md`, `0002-cli-runner-flags.md`, `0003-hook-mapping.md`, `0004-graphify.md`, `0005-opencode-discovery.md` | なし（文書） | 1 | なし |
| T04 | Eval / Prompt-Skill fixture。E01〜E10（D6 を適用）、A01〜A08 の入力、TRIGGER± / BOUNDARY / OUTPUT / TOOL / REGRESSION / SECURITY / CONTEXT、悪意ある文書（`.fixture` サフィックス、D16） | `tests/fixtures/eval/**`, `tests/fixtures/prompt_skill/**`, `tests/fixtures/security/**`, `docs/evals.md` | なし（データ）。T25 で「ダミー実装なら FAIL」を検証 | 1 | なし |

W1 の barrier 後、オーケストレータが `git tag v1-baseline 4c5ac19` と push を行う（v1 最終コミット。リモート取得後に訂正）。

### P1: コア・契約・CLI 基盤（W2〜W4）

| # | タスク | 所有ファイル | テスト方針 | wave | 依存 |
|---|---|---|---|---|---|
| T05 | **全契約**。dataclass / StrEnum / Protocol と JSON Schema。対象は TaskSpec、WorkUnit、Edge、Verdict、UnitState（10状態と許可遷移表）、Result（OK / NOT_FOUND / UNSUPPORTED / ERROR）、Evidence、RunContext、RunResult、TerminalState、CanonicalSpec、HostCapability（NATIVE / ADAPTED / CI_ONLY / UNSUPPORTED / UNVERIFIED）、GeneratedPlan、DiscoveryReport、ModuleManifest、Module Protocol、AuthoringRecord（状態と遷移）、ApprovalToken、PlannedChange | `src/seh/contracts/**`, `src/seh/schemas/**`, `tests/**/contracts/` | U（Schema の正常・異常、不正遷移の拒否） | 2 | T01 |
| T06 | subprocess 安全層。argv 配列、cwd / env allowlist（`CLAUDECODE` 系を除外）、stdin 渡し、stdout / stderr の分離と上限、タイムアウト、プロセスグループ kill、キャンセル | `src/seh/runtime/__init__.py`, `src/seh/runtime/process.py`, `tests/**/process/` | U / I（`sleep`・`yes` で残存プロセス 0 を確認、CLI-007） | 2 | T01 |
| T07 | 秘匿（redaction）と trace。秘密値のマスク、JSONL trace（run / task / node ID と evidence digest）（artifact 保存は T13 へ移管） | `src/seh/redaction.py`, `src/seh/trace.py`, `tests/**/trace/` | U（ダミー秘密値は文字列連結で組む。T08 / FR-049 / FR-050） | 2 | T01 |
| T08 | Config。`.harness/config.toml` の読込、Schema、既定値、Minimal / Balanced / Full、`config show` と `config set --plan` | `src/seh/config.py`, `src/seh/commands/config.py`, `tests/**/config/` | U（不正な key / 型 / 値の拒否、`auto_low_risk` は受理するが適用しない） | 3 | T05 |
| T09 | Module Registry。manifest のパース、依存と競合の解決、Capability 台帳、`module list` と `module enable --plan`、標準 manifest | `src/seh/registry.py`, `src/seh/modules/**`, `src/seh/commands/module.py`, `tests/**/registry/` | U（循環、重複 Provider、API 不一致、manifest 読込時にコードを実行しない） | 3 | T05 |
| T10 | Policy。R0 / R1 / R2 分類、tool / command allowlist、承認トークン（scope・有効期限・対象 digest に紐づく、`--yes` では R2 不可） | `src/seh/policy.py`, `tests/**/policy/` | U（NFR-001 の負例10件、T12） | 3 | T05 |
| T13 | AgentRunner 基盤。`CliAgentRunner` Protocol、Vendor Adapter の基底（`build_argv` / `parse_event` / `detect_terminal_status` / `normalize_usage`）、`cli_capability` probe、テスト用 FakeCliRunner | `src/seh/runtime/agent_runner.py`, `src/seh/runtime/runners/__init__.py`, `src/seh/runtime/runners/base.py`, `src/seh/runtime/cli_capability.py`, `src/seh/runtime/runners/fake.py`, `src/seh/artifacts.py`（T07 から移管: Evidence 型が T05 依存のため）, `tests/**/runner_base/` | U（usage 欠損は UNKNOWN、CLI-011） | 3 | T05, T06 |
| T11 | Hook イベント。stdin JSON を完全にパースし、D11 の fail-closed / fail-open を実装。v1 の安全フックを Python へ移植（破壊コマンド、機密 / 設定保護、commit 前の秘密スキャン）。Hook シム（`seh` 不在時は警告して通過） | `src/seh/events.py`, `src/seh/commands/hook.py`, `src/seh/templates/hooks/**`, `tests/**/events/` | U / I（malformed → exit 2、未知イベント、シム） | 4 | T07, T10 |
| T12 | `seh doctor` 基盤。check モジュール列挙型の構成、config / 参照 / module 状態 / バージョン不一致（D8）、`--context`（NFR-011）、`--format json` | `src/seh/doctor/**`, `src/seh/commands/doctor.py`, `tests/**/doctor/` | U / I（オフラインで動く、FR-052） | 4 | T08, T09, T07 |
| T14 | Ownership。hash manifest、三者差分、atomic write、transaction / snapshot / restore、symlink の realpath 判定 | `src/seh/ownership.py`, `tests/**/ownership/` | U / I（途中 kill 後の復旧、NFR-004 / T09） | 4 | T05 |
| T15 | スタック検出。v1 の harness-init（languages / task-runners）の知見をコード化し、言語・タスクランナー・CI / format / lint / 型コマンド・既存設定を read-only で検出 | `src/seh/init/__init__.py`, `src/seh/init/detect.py`, `tests/**/detect/` | U / I（Python / Node / Go / Rust の小 fixture。実在コマンドだけを選ぶ） | 4 | T05 |

### P2: Host render・init・migration・sync（W5〜W6）

| # | タスク | 所有ファイル | テスト方針 | wave | 依存 |
|---|---|---|---|---|---|
| T16 | Claude HostAdapter（probe / render / lint / discover）。`.claude/skills`、`agents`、`rules`、`settings.json`、`CLAUDE.md` の管理ブロック | `src/seh/providers/__init__.py`, `src/seh/providers/hosts/__init__.py`, `src/seh/providers/hosts/claude.py`, `tests/**/host_claude/` | U（スナップショット。frontmatter が正しい） | 5 | T05, T03 |
| T17 | AGY HostAdapter。`.agents/skills`、`.agents/rules`、`.agents/hooks.json`、`AGENTS.md` / `GEMINI.md`。surface 検出、`managed_cli=disabled` | `src/seh/providers/hosts/antigravity.py`, `tests/**/host_agy/` | U（Claude 固有キーを転写しない、FR-064） | 5 | T05, T03 |
| T18 | Codex HostAdapter。`.agents/skills`、`AGENTS.md`、`.codex/`（必要時）、Hook は CI_ONLY 判定 | `src/seh/providers/hosts/codex.py`, `tests/**/host_codex/` | U | 5 | T05, T03 |
| T19 | OpenCode HostAdapter。`.opencode/agents`、`.opencode/plugins/seh-guard.ts`、Claude 互換パスの扱い（T03-0005 に従う） | `src/seh/providers/hosts/opencode.py`, `src/seh/templates/hosts/opencode/**`, `tests/**/host_opencode/` | U（plugin はスナップショットのみ、D11） | 5 | T05, T03 |
| T21 | `seh init`。`--plan`（read-only・Git / HOME 差分 0）、プロファイル選択、hosts / provider 選択、plan → diff → approve → apply、非対話は承認トークン必須、失敗時の原子的復元 | `src/seh/init/planner.py`, `src/seh/init/apply.py`, `src/seh/commands/init.py`, `tests/**/init/` | I（T01 / T09 / FR-001 / 006） | 6 | T08, T14, T15, T16〜T19 |
| T22 | Migration。inventory / planner（D12 の分類規則）/ apply / rollback、`migrate plan / apply / rollback` | `src/seh/migration/__init__.py`, `inventory.py`, `planner.py`, `apply.py`, `rollback.py`, `src/seh/commands/migrate.py`, `tests/**/migration/` | I（v1 fixture、手編集 → CONFLICT、symlink、途中 kill、T10 / E10） | 6 | T14, T02 |
| T23 | `seh sync --hosts`。正本 → 生成物の一方向変換、share / copy / link / suppress の計画、collision 検出（FR-078）、`generated.lock.json` | `src/seh/sync.py`, `src/seh/providers/hosts/discovery.py`, `src/seh/commands/sync.py`, `tests/**/sync/` | I（4ホスト併存、手編集ブロックの保持、部分失敗時のロールバック、T15 / FR-082） | 6 | T14, T16〜T19 |
| T24 | 参照監査。削除済み Skill / Agent / Rule 名のダングリング検出（D14 の除外パス） | `src/seh/audit.py`, `tests/**/audit/` | U | 6 | T02 |

### P3 / P3A: Eval・Tool・Output Contract・Authoring Guard（W7〜W9）

| # | タスク | 所有ファイル | テスト方針 | wave | 依存 |
|---|---|---|---|---|---|
| T25 | 決定論的 Checker と fixture loader。exit code / 構造 / 差分スコープ / 制約 / 安全で PASS / FAIL を判定。「エラーなし」だけでは PASS にしない（FR-036） | `src/seh/evals/__init__.py`, `src/seh/evals/fixtures.py`, `src/seh/evals/checker.py`, `tests/**/checker/` | U（T04 の fixture、ダミー実装は FAIL、E08 / T07） | 7 | T05, T04 |
| T26 | Tool Registry と標準 Tool。schema 検証 → policy 認可 → 実行 → 出力検証。`git_ops`、`test_runner`、`policy_checker` | `src/seh/tools/**`, `tests/**/tools/` | U（不正入力、権限外） | 7 | T05, T10 |
| T27 | Output Contract。CLI 出力 JSON の Schema 検証、`INVALID_OUTPUT`、途中切断、reasoning を要求しない契約 | `src/seh/runtime/output.py`, `tests/**/output/` | U（FR-024 / 027） | 7 | T05 |
| T39 | Workflow DAG。NodeSpec と input_bindings、サイクル / 欠落 / 型不一致の検出、修正ループを DAG に入れない | `src/seh/runtime/graph.py`, `tests/**/graph/` | U（FR-012 / 013） | 7 | T05 |
| T28 | Eval runner / variants V0〜V5 / report / `eval run・compare`。N 試行、tokens・時間・コスト・再試行（不明は UNKNOWN）、holdout 隔離、未計測値を捏造しない | `src/seh/evals/runner.py`, `variants.py`, `report.py`, `src/seh/commands/eval.py`, `tests/**/eval_runner/` | I（FakeCliRunner。T11 の比較で昇格拒否） | 8 | T25, T13, T27 |
| T30 | Authoring の classify と spec。対象パス（4ホスト + `.harness/spec`）→ text_only / behavioral / high_risk、AuthoringRecord の検証 | `src/seh/authoring/__init__.py`, `classify.py`, `spec.py`, `tests/**/authoring_classify/` | U（権限変更を text_only にしない） | 8 | T05 |
| T31 | Authoring の inventory。既存 Skill / CLI / MCP との重複判定と配置判断（`NOT_NEEDED`） | `src/seh/authoring/inventory.py`, `tests/**/authoring_inventory/` | U（A01 / FR-054 / 068） | 8 | T05 |
| T32 | Authoring の lint。ホスト別の frontmatter / 名称衝突 / 未認可キー / 過剰権限 / 必須契約（Goal・Inputs・Boundaries・Output・Feedback）/ Context 重複 | `src/seh/authoring/lint.py`, `tests/**/authoring_lint/` | U（A04 / A05 / FR-057 / 059） | 8 | T05 |
| T33 | Authoring の eval / gate / promote / rollback と `seh author` 全サブコマンド。04 §6.3 の不変条件、`BLOCKED_NO_EVAL` / `NEEDS_HUMAN`、`.harness` 不在時は `NOT_CONFIGURED` | `src/seh/authoring/eval.py`, `gate.py`, `promote.py`, `src/seh/commands/author.py`, `tests/**/authoring_gate/` | I（A03 / A07 / FR-070） | 9 | T28, T30〜T32, T14 |
| T34 | Authoring Gate CI。`.github/workflows/authoring-gate.yml`（`seh author lint --changed`、no-op 規則）と NOT_ENFORCED の明記 | `.github/workflows/authoring-gate.yml`, `tests/**/authoring_ci/` | I（ワークフローの静的検査） | 9 | T33 と同 wave だが CLI 契約（T05）にのみ依存 |
| T35 | Claude CLI runner。`claude -p --output-format stream-json`、`--json-schema` probe、終端イベント必須、soft-deny 検出 | `src/seh/runtime/runners/claude_cli.py`, `tests/**/runner_claude/` | U（記録済み JSONL、CLI-002 / 006）+ R | 9 | T13 |
| T36 | Codex CLI runner。`codex exec --json -C`、`--output-schema`、`--sandbox` probe | `src/seh/runtime/runners/codex_cli.py`, `tests/**/runner_codex/` | U（CLI-003）+ R | 9 | T13 |

### P4 / P6: Managed Runtime・Provider（W10〜W12）

| # | タスク | 所有ファイル | テスト方針 | wave | 依存 |
|---|---|---|---|---|---|
| T37 | OpenCode CLI runner。`opencode run --format json`、セッション継続は任意 Capability | `src/seh/runtime/runners/opencode_cli.py`, `tests/**/runner_opencode/` | U（CLI-004）+ R | 10 | T13 |
| T38 | AGY CLI runner。Policy Gate を先に通し、既定 `POLICY_BLOCKED` で起動しない。別ホストへ黙って振り替えない | `src/seh/runtime/runners/antigravity_cli.py`, `tests/**/runner_agy/` | U（CLI-005 / FR-093 / 099） | 10 | T13, T10 |
| T40 | Scheduler。依存待ち、`max_parallel`、予算、deadline、cancel、全体停止条件 | `src/seh/runtime/scheduler.py`, `tests/**/scheduler/` | U / I（FR-014 / 051、T03） | 10 | T39 |
| T41 | Worktree。ユニット専用 worktree、write_allowlist の差分検査、merge、collision 検出（自動で隠さない） | `src/seh/runtime/worktree.py`, `tests/**/worktree/` | I（一時 repo、CLI-009 / FR-015 / 021 / 096） | 10 | T05 |
| T42 | Repair と checkpoint。Generate → Evaluate → Repair を最大3回、失敗ユニットだけ再実行、永続 state、再開時は再検証してから進む | `src/seh/runtime/repair.py`, `src/seh/runtime/checkpoint.py`, `tests/**/repair/` | U / I（T04 / T05 / T14 / CLI-008） | 11 | T25, T40, T13 |
| T51 | CodeIntel の基底と source fallback（git / rg / ast）。UNSUPPORTED と空結果を区別 | `src/seh/providers/codeintel/__init__.py`, `base.py`, `source_fallback.py`, `tests/**/codeintel_base/` | U（FR-037 / 038） | 11 | T05 |
| T54 | Memory の File / Engram provider。共通 API テスト（Engram は接続モック）、provider 切替時に既存データを保持 | `src/seh/providers/memory/**`, `tests/**/memory/` | U / I（T13 / FR-040） | 11 | T05 |
| T55 | Knowledge。domain.md の生成と遅延・部分取得（FR-039）、verified_constraints の読み取り API | `src/seh/knowledge.py`, `tests/**/knowledge/` | U | 11 | T05 |
| T43 | Managed オーケストレータ。splitter（verified_constraints を入力）、worker / code / gate ノード、最終 Gate と Evidence bundle（無証拠 SUCCESS と R2 の無人実行を拒否）、`work run / status / resume` | `src/seh/runtime/managed.py`, `src/seh/runtime/splitter.py`, `src/seh/runtime/gate.py`, `src/seh/commands/work.py`, `tests/**/managed/`, `tests/e2e/managed/` | E（mock CLI。T03〜T05 / T07 / T12 / T14 / E05 / E09） | 12 | T42, T41, T27, T35〜T38, T55 |
| T52 | CodeGraph adapter。既存バイナリでのスモークは一時 HOME で実行し、バイナリが無ければ skip | `src/seh/providers/codeintel/codegraph.py`, `tests/**/codeintel_codegraph/` | U + I | 12 | T51, T03 |
| T53 | Graphify adapter。T03-0004 の CLI 契約に従い fake でテスト。未導入なら ERROR と導入案内 | `src/seh/providers/codeintel/graphify.py`, `tests/**/codeintel_graphify/` | U（E06 / T02） | 12 | T51, T03 |
| T56 | Install audit。外部インストーラが入れる Hook / Skill の二重登録を検出（FR-045 / P6-04） | `src/seh/install_audit.py`, `tests/**/install_audit/` | U | 12 | T23 |

### P4A / P5 / P6A: Authoring 統合・テンプレート縮約（W13〜W14）

| # | タスク | 所有ファイル | テスト方針 | wave | 依存 |
|---|---|---|---|---|---|
| T45 | Authoring lifecycle。Managed 側は EXPLORE → PLAN → APPROVE → BASELINE → WRITE → VERIFY → COMPARE → PROMOTE の状態機械で、承認前の Write を拒否。Native 側は PreToolUse の早期検出と Stop の NEEDS_EVAL（Stop の回数上限あり） | `src/seh/authoring/lifecycle.py`, `src/seh/events.py`, `tests/**/authoring_lifecycle/` | U / I（A02 / A06） | 13 | T33, T43, T11 |
| T46 | 正本の Skill。`work`（タスク分類 → native / managed の提案、authoring ルート、`seh` を呼ぶ）と `harness-init`（`seh init` を呼ぶ）。04 の契約を満たす薄い SKILL.md | `src/seh/templates/spec/skills/**` | U（T32 の lint が PASS）。Eval ケースは T04 を参照 | 13 | T32 |
| T47 | 正本の Agent。implementer / reviewer（読み取り専用、review_type）/ fixer / evolver（未承認の設定変更は不可）の YAML（ロール・権限・model / effort） | `src/seh/templates/spec/agents/**` | U（lint、最小権限、FR-019） | 13 | T32 |
| T48 | 正本の instructions と rules。core.yaml（短い全体方針と Authoring の数行ルール）、engineering / testing、architecture（条件付き） | `src/seh/templates/spec/instructions/**`, `src/seh/templates/spec/rules/**` | U（`--context` 測定で v1 基準値より小さい、FR-067 / NFR-011） | 13 | T32, T02 |
| T49 | Hook / 権限の render 統合。4ホストの hook mapping（D11 の表）、permission mapping（未対応の deny を黙って allow にしない、FR-080） | `src/seh/providers/hosts/hooks_map.py`, `src/seh/providers/hosts/permissions_map.py`, `tests/**/host_mapping/` | U（4ホストのスナップショット） | 14 | T16〜T19, T11 |
| T57 | Context 配置の最適化。常時 / 遅延 Context の計測、CLAUDE.md 内の長い手順の検出、skills と commands の重複、組み込み名との衝突（P6A） | `src/seh/doctor/context_placement.py`, `tests/**/context_placement/` | U | 14 | T12 |
| T58 | Evolution の observe。trace とフィードバックの分類・重複排除 | `src/seh/evolution/__init__.py`, `observe.py`, `tests/**/evolution_observe/` | U（P7-01） | 14 | T07, T54 |
| T59 | Evolution の propose。候補を独立 worktree で生成し、保護パス（policy / 承認設定）を書込不可にする | `src/seh/evolution/propose.py`, `tests/**/evolution_propose/` | I（P7-02） | 14 | T41, T10 |
| T50 | モード文書（native と managed の保証差、NOT_ENFORCED、AGY の制約） | `docs/modes.md` | なし（文書） | 14 | T43 |

### P7: 自己進化（W15）

| # | タスク | 所有ファイル | テスト方針 | wave | 依存 |
|---|---|---|---|---|---|
| T60 | Benchmark。baseline → candidate → regression → holdout を Eval runner 経由で実行し、改善と悪化を同時に表示 | `src/seh/evolution/benchmark.py`, `tests/**/evolution_benchmark/` | I（T11 / FR-032 / 033） | 15 | T28, T59 |
| T61 | promote / rollback / lifecycle と learning-edge。未承認は無効、stale の退役（ユーザー作成知識は消さない）、`verified_constraints.jsonl` へ書込み | `src/seh/evolution/promote.py`, `rollback.py`, `lifecycle.py`, `learning.py`, `tests/**/evolution_promote/` | I（FR-042 / 043） | 15 | T60, T55 |
| T62 | `seh evolve`（propose / benchmark / promote / rollback）と Authoring Gate の連携（P7-07 / A08 / FR-066） | `src/seh/commands/evolve.py`, `tests/**/evolution_cli/` | E（mock） | 15 | T61, T33 |
| T63 | Compatibility レポート。`compatibility.json`、`doctor --hosts all`（論理 Skill の Discovery、hash、実効権限、FULL / PARTIAL / BLOCKED の根拠） | `src/seh/compatibility.py`, `src/seh/doctor/hosts.py`, `tests/**/compatibility/` | I（CLI-010 / FR-075 / 081） | 15 | T23, T49, T35〜T38 |

### P8: リリース準備と dogfooding（W16〜W18）

| # | タスク | 所有ファイル | テスト方針 | wave | 依存 |
|---|---|---|---|---|---|
| T64 | サンプル repo（Python / TS）と E2E マトリクス。新規 / v1 移行 / 権限制限 / 4ホスト共存 / Authoring Gate | `tests/fixtures/samples/**`, `tests/e2e/test_*.py`（`managed/` 以外） | E（mock） | 16 | 全 P1〜P7 |
| T65 | ドキュメント。README（v2 導入、復旧手順、SDK 不要、AGY 制限、NOT_ENFORCED）、`docs/architecture.md`（`_reference.md` の設計思想を統合）、`docs/migration-v1-to-v2.md`、`docs/provider-compatibility.md`、`docs/runbook.md`、`CHANGELOG.md`、`.gitignore` の `.desloppify/` 削除 | `README.md`, `docs/architecture.md`, `docs/migration-v1-to-v2.md`, `docs/provider-compatibility.md`, `docs/runbook.md`, `CHANGELOG.md`, `.gitignore` | U（T24 の参照監査を docs に適用） | 16 | 全 P1〜P7 |
| T66 | 実 CLI スモークのテスト群（`tests/real/`、`real` marker）。一時 fixture repo と env allowlist | `tests/real/**` | R（オーケストレータが D4 の上限内で実行） | 16 | T35〜T38, T43 |
| T67 | **dogfooding 計画（停止点）**。`uv tool install -e .` を実行し、`seh init --hosts all --plan` と `seh migrate plan --from v1` の結果を `docs/dogfooding-plan.md` に記録して停止する（`.harness/config.toml` の内容は D13） | `docs/dogfooding-plan.md` | なし（計画の提示） | 17 | T64〜T66 |
| T68 | apply 後の証拠収集と残課題の修正。doctor、hook 結合、参照監査、Discovery、`/work` の Authoring Eval（R）、rollback 検証（一時 clone） | apply が生成したファイル一式（`.harness/**`, `.claude/**`, `.agents/**`, `.opencode/**`, `.codex/**`, `CLAUDE.md`, `AGENTS.md`）、`docs/dogfooding-report.md` | E + R | 18 | ユーザーの apply |

### wave 内の独立性（同一 wave 内で所有ファイルが互いに素であることの根拠）

- **W1**: 書く場所がタスクごとに分かれています。T01 はコードと CI、T02 は `docs/v1-inventory.md` と `docs/baseline`、T03 は `docs/decisions`、T04 は `tests/fixtures`。T02 の `src/seh/migration/v1_known_paths.json` は T01 の所有外です。
- **W2**: T05 は `contracts/` と `schemas/`、T06 は `runtime/process.py`、T07 は `redaction.py`・`trace.py`。重なりはありません（`artifacts.py` は Evidence 型に依存するため W3 の T13 へ移管）。
- **W3**: T08（config）、T09（registry）、T10（policy）、T13（runner 基盤）は、どれも別ファイルとテストディレクトリです。T13 の `runtime/runners/__init__.py` は T13 だけが作ります。
- **W4**: T11（events・hook）、T12（doctor）、T14（ownership）、T15（init/detect）。`init/__init__.py` は T15 が所有し、T21 は後続の wave です。
- **W5**: 4ホストがそれぞれ別ファイルです。`providers/__init__.py` と `providers/hosts/__init__.py` は T16 だけが所有します。
- **W6**: T21 は init/、T22 は migration/、T23 は sync・discovery、T24 は audit。`migration/v1_known_paths.json` は W1 で T02 が作成済みで、T22 は読むだけです。
- **W7〜W8**: `evals/__init__.py` は T25 が所有し、T28 は後続の wave。`authoring/__init__.py` は T30 が所有します。
- **W9〜W15**: 各タスクの所有ファイルは表のとおり互いに素です。`events.py` は T11（W4）と T45（W13）で、wave が違います。`doctor/` 配下はタスクごとに別ファイルで、check の登録は各モジュールで自己完結させます（共有のリストを持たない）。
- **4件を超える wave**: W14（5件）だけです。プロトコルに従い、同じ wave の中で2回に分けて起動します（4件 + 1件）。

### barrier・push・レビューの時点

| 時点 | 内容 |
|---|---|
| 各 wave 後 | 境界検証 → `CI_CHECK_CMD` → wave コミット（件名は日本語、動詞始まり） |
| W1 後 | `v1-baseline` タグ、push（P0 完了） |
| W4 後 | push。`/self-review`（契約・policy・hook は誤ると後続すべてに波及するため） |
| W6 後 | push（P1 / P2 完了） |
| W9 後 | push（P3 / P3A 完了） |
| W12 後 | 実 CLI 接続スモーク（D4 の枠：各ホスト1回）、push、`/self-review`（Managed runtime） |
| W15 後 | push（P4A / P5 / P6 / P7 完了） |
| W16 後 | `/self-review`（全体）、push |
| W17 | **停止**。dogfooding 計画を提示し、ユーザーの対話 apply を待つ |
| W18 後 | 最終 CI、`/self-review`、完了報告、push |

## アーキテクチャへの影響

- このリポジトリは「`.claude/` をコピーするテンプレート」から「Python パッケージ `seh` + 生成物」に変わります。P0〜P7 の間、v1 の `.claude/` は不変で、開発セッションは v1 のまま動きます。
- 依存方向は上記のレイヤー図に従います。`.claude/rules/architecture.md`（v1 のプレースホルダ）は P8 の dogfooding 後、`.harness/spec/rules/architecture` から実態どおりに生成されます。
- 正本は `src/seh/templates/spec/`（配布テンプレート）です。dogfooding 後は、このリポジトリの `.harness/spec/` が正本になります。

## リスク

- **v1 Hook が開発作業を止める**（秘密スキャン・設定保護）: D15 の命名規約とダミー値の連結を、すべてのワーカープロンプトに入れます。
- **実 CLI のフラグやイベント形式が想定と違う**: T03 で `--help` の実測と公式資料を確認し、runner は記録済みの JSONL fixture でテストします。実スモークの失敗は `UNVERIFIED` として報告し、仕様を推測で埋めません。
- **契約（T05）の欠陥が後続すべてに波及する**: W4 後の `/self-review` で契約を重点的に見ます。後続のワーカーが契約の変更を必要とした場合は「境界外の変更が必要」として返させ、オーケストレータが契約変更タスクを差し込みます。
- **タスク数が多く（約60件）長時間かかる**: wave ごとのコミットとフェーズごとの push で、途中から再開できるようにします。進捗は Engram に保存します。
- **AGY・Codex の Hook 仕様を確認できない**: `CI_ONLY` / `UNVERIFIED` に倒し、FULL と表示しません。
- **dogfooding apply でセッションが壊れる**（fail-closed の Hook が誤作動するなど）: snapshot、`seh migrate rollback`、`git checkout v1-baseline -- …` の3段の復旧手順を T67 で提示します。
- **pyright strict 寄りの設定で async / Protocol の型エラーが続出する**: T01 で `typeCheckingMode = "standard"` に確定し、以後変更しません。

## 実行中の計画変更記録

| 日時 | 変更 | 理由 |
|---|---|---|
| W2 | `src/seh/artifacts.py` を T07 → T13（W3）へ移管 | Evidence 型が同 wave の T05 に依存するため |
| W5 前 | `providers/__init__.py`・`providers/hosts/__init__.py`・`providers/hosts/common.py` をオーケストレータが先行作成（b32089c） | Codex/AGY/OpenCode が共有する `.agents/skills`・`AGENTS.md` 生成を1箇所に置き、W5 の4並列を可能にするため |
| W6 前 | T21（`seh init`）を W6 → W7 へ移動。正本 spec ローダー `src/seh/spec_loader.py` を T23 の所有に追加 | init は spec ローダーと sync 計画に依存し、それらは W6 の T23 が作るため |
| W6 前 | v2.0 の承認方式を「対話モードの確認プロンプトのみ」に確定。非対話で承認が必要な適用（R2・既存ファイル置換）は拒否し対話実行を案内する。承認トークン発行 CLI は v2.0 では作らない（契約 `ApprovalToken` と Policy の検証は残す） | AI による承認の自己発行を構造的に不可能にしつつ、要件 02 §10（`--yes` だけで危険操作を許可しない）を満たす最小構成 |
