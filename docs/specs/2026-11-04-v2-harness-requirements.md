# 要件定義: self-evolve-harness v2.0 再設計（P0〜P8 全体・設計 v1.3 準拠）

## 目的

`docs/design/v2/`（設計 v1.3: 01 改修方針書 / 02 要件定義書 / 03 実装計画書 / 04 Skill・Prompt 作成標準 /
05 マルチホスト互換性 / 06 CLI ランナー・SDK 任意化 / examples）に従い、v1 テンプレート（Markdown 手順書中心・
9 Skill / 9 Agent）を、Python CLI `seh` が実行制御・検証・評価・移行・Authoring Gate を担う v2.0
（論理 2 Skill / 4 Agent・4 ホスト生成・CLI First）へ作り替える。

本書は設計書を**正**とし、本セッションの決定事項による**差分・具体化（D1〜D18）だけ**を定める。
差分が無い項目は設計書の FR-001〜FR-100 / NFR-001〜015 / DoD / テスト（T01〜T15, A01〜A08, CLI-001〜012）がそのまま適用される。
設計書内の版間差分（v1.0 の SDK 案 vs v1.3 の CLI First 等）は **v1.3 の記述を優先**する（03 §15・§16、06 が正式な実行契約）。

## 成功基準

設計書 02 §11 DoD（+ Authoring 2 項目）・04 §8・05 §7・06 §9 を、下記差分を適用して満たすこと:

- [ ] 既存 Skill の削除/統合と、README・CLAUDE.md・AGENTS.md・doctor・Hook の参照更新が完了し、参照監査（D14 の除外パスを除く）でダングリング参照 0
- [ ] 新規導入／既存導入／設定切替／アンインストールが dry-run → 承認 → 復元できる
- [ ] 旧ハーネスの個人設定・ユーザー独自 Skill に破壊的変更がない（`settings.local.json` は不変）
- [ ] 論理 4 Subagent（implementer / reviewer / fixer / evolver）が最小権限で4ホスト向けに生成され、標準 Subagent（Explore/Plan 等）を無用に複製しない
- [ ] `codegraph` / `graphify` / `none` の3経路がテスト済み（graphify は fake、codegraph は既存バイナリで実スモーク）
- [ ] Managed Runtime（CliAgentRunner）で DAG 依存・上限並列・修正3回停止・ユニット限定差し戻し・checkpoint 再開が E2E（mock CLI）PASS。claude / codex / opencode の実 CLI スモークが PASS（`BLOCKED_AUTH` は**未達**として報告）、AGY は `POLICY_BLOCKED`。v2.0 は AGY 制約により**非フル（PARTIAL）リリース**として宣言する
- [ ] Eval の V0〜V5 比較が同一 Fixture で **mock CLI により**実行可能（非対応は skip を明示）
- [ ] Authoring Guard（`seh author`）が Skill/Prompt/Rule/Agent/Hook 変更を4ホスト分検出・分類・lint し、評価証拠なしの昇格を拒否する（A01〜A08 PASS）
- [ ] 出力構造・全 Must Gate・リスク承認・ログ秘匿の検査が PASS
- [ ] 自己進化は独立評価と明示承認がなければ昇格できない
- [ ] 4ホスト（Claude / AGY / Codex / OpenCode）の生成物と `compatibility.json` が出力され、未検証機能を FULL と表示しない
- [ ] このリポジトリ自身への4ホスト dogfooding の apply 計画（差分・snapshot・rollback 手順）を提示し、**ユーザーが対話で apply した後**に D13 の証拠を揃える。v1 は `v1-baseline` タグから復元できる
- [ ] 公式ドキュメント（README / `docs/`）とサンプルプロジェクトで導入・障害復旧手順が再現できる
- [ ] `CI_CHECK_CMD` が全 PASS（出力を証拠として提示）

## 機能要件（設計書からの差分・具体化）

### D1. スコープ
- 設計書 P0〜P8（P0A / P3A / P4A / P6A を含む）をすべて実装する。
- 優先度: **Must と Should を実装**する。Could の FR-026（`<reply>`+stop sequence の API Adapter）は**実装しない**（v1.3 01 §5 で「低レベル API Adapter は将来の任意モジュール」）。
- SDK アダプター（`[sdk]`）は設定キーのみ受け付け、実装しない（FR-094・06 §8）。

### D2. ツールチェーン
- Python 3.11+（`requires-python = ">=3.11"`、pyright `pythonVersion = "3.11"`）。CI は 3.11 と 3.13 のマトリクス。
- uv / pytest / ruff / pyright。ツール設定はすべて `pyproject.toml` の `[tool.*]` に置く（`ruff.toml` / `pyrightconfig.json` 等の独立ファイルは作らない。v1 の設定保護 Hook に阻まれるため）。
- CLAUDE.md の CI コマンド:
  - `CI_CHECK_CMD`: `uv run ruff check . && uv run ruff format --check . && uv run pyright && uv run pytest -m "not real"`
  - `CI_FIX_CMD`: `uv run ruff check --fix . && uv run ruff format .`
- P0 の `pyproject.toml` に最初から入れる設定: pytest `markers = ["real: 実 CLI スモーク（SEH_REAL_SMOKE=1 必須）"]`・`testpaths = ["tests"]`・`norecursedirs`（`tests/fixtures`）、ruff `extend-exclude`（`tests/fixtures`, `docs/design`）、pyright `exclude`（同）と `pythonVersion = "3.11"`。
- `pyproject.toml` の `[tool.*]` は P0 で確定後、変更禁止（変更が必要なら停止して報告）。`dependencies` / dev グループへの追加は可。必須 dependencies に SDK（claude-agent-sdk / codex-sdk / opencode SDK 等）を入れない（FR-086）。
- P0 最初の wave で `pyproject.toml` と最小スモークテスト（`seh --help`）を作り、以降の barrier で `CI_CHECK_CMD` が成立する状態にする。

### D3. 移行方式（同一リポで段階移行）
- P0 で `4c5ac19`（origin/main 上の v1 最終コミット。当初 988a019 としていたが、リモートに未取得の v1 コミット3件があったため訂正）に `v1-baseline` タグを打ち、push する。「Git clean」判定から未追跡の `.agents/` は除外する。
- P0〜P7 の間、v1 の `.claude/`（skills / agents / rules / settings.json）はリポジトリ実体として**変更しない**。P5 の Skill/Agent/Rule 縮約は `src/seh/templates/`（および `.harness/spec/` の正本テンプレート）側だけで行う。
- リポジトリ実体の v1 資産の削除・置換は **P8 の dogfooding apply（ユーザー実行、D13）に限る**。
- P0〜P7 はリポジトリ直下に `.harness/` を作らない。正本テンプレートは `src/seh/templates/spec/` に置く。Authoring Gate（CLI・`authoring-gate.yml`）は `.harness/config.toml` が無いリポジトリでは no-op（`NOT_CONFIGURED` を出力して exit 0）。
- push 条件はローカル `CI_CHECK_CMD` PASS。GitHub Actions の失敗は次 wave で修正する。

### D4. 実モデル呼び出し（CLI First）
- CI・単体/結合/E2E テストはすべて **mock CLI（fake subprocess / 記録済み JSON・JSONL fixture）**。
- 実 CLI スモークは pytest marker `real` かつ環境変数 `SEH_REAL_SMOKE=1` の両方が揃ったときだけ実行する。`CI_CHECK_CMD` は `-m "not real"` を既定とし、認証の有無で自動実行しない。
- 実 CLI の利用上限: **claude / codex / opencode 各ホスト合計5回以内、1回 600 秒以内**。内訳は P4 接続スモーク 1回 + P8 の `/work` Authoring Eval 最小セット（positive 1 / negative 1 / outcome 1）+ 予備 1。それ以外のケースは `NOT_RUN` と記録する。未認証は `BLOCKED_AUTH` として報告し、PASS 扱いしない。
- 実 CLI スモーク（`real` marker）に限り次を許可・規定する:
  - 実 HOME を読む（認証情報: Keychain、`~/.claude*`、`~/.codex/`、`~/.local/share/opencode/`）。CLI 自身による履歴追記（例: `~/.claude.json`）は許容。
  - 子プロセス env は allowlist（`PATH`, `HOME`, `LANG`, `TERM`, `USER`, `TMPDIR` 等）で組み立て、`CLAUDECODE` / `CLAUDE_CODE_*` は渡さない（入れ子起動対策）。
  - cwd は一時ディレクトリの fixture リポジトリに限る（本リポジトリ直下では実行しない）。
- **AGY のセッション起動（`agy -p` / 対話起動）は実行しない**。`agy --version` / `--help` による probe は許可。既定 `managed_cli = "disabled"` → `POLICY_BLOCKED` をテストで確認する（FR-093 / CLI-005）。
- P0A の出口条件「v1 Skill の Trigger/Outcome 基準値を記録」は「Eval ケースの作成のみ。基準値は `NOT_RUN`」に読み替える。
- モデル呼び出しを伴う P0 ベースライン実測と V0〜V5 の実比較は行わない。`seh eval run` / `seh eval compare` と実行手順書（`docs/`）を用意し、実計測はユーザーが後で行う。**未計測の数値をレポートに書かない**。
- モデルを使わない計測（NFR-005 の CLI 速度、NFR-011 / FR-067 の常時 Context 量）は P0 で実測し基準値を記録する。
- 設計書の P4-01「許可済み実機を実行」/ P8-07「実測レポート」/ 03 §13「実機 E2E」は「mock で PASS + 上記の実スモーク。範囲外は skip を明示」に読み替える。

### D5. Host（4ホスト）
- 設計 v1.3 どおり Claude Code / AGY / Codex / OpenCode。各ホストの生成形式・CLI フラグは**インストール済み CLI の `--help` / `--version` と公式資料**で P0 に確認し、決定記録 `docs/decisions/` に残す（確認時の版: claude 2.1.318 / codex 0.166.0 / opencode 1.19.5 / agy 1.4.12）。確認できない機能は推測で生成せず `UNVERIFIED` / `UNSUPPORTED`。
- AGY の Subagent 定義形式・Codex の Hook 等、設計書で「検証してマッピング」とされた項目も同様。
- `generated.lock.json` / `compatibility.json` には CLI の**コマンド名とバージョンのみ**を記録し、絶対パスを書かない（cmux シム経由でパスがセッションごとに変わるため）。
- lock ファイルは `.harness/generated.lock.json` に一本化する（03 の `module.lock.json` の内容＝解決済み module version もここに含める）。
- **4ホスト共存の重複 Discovery（FR-078）**: P0 で OpenCode の Claude 互換パス（`.claude/skills`）探索を設定で無効化できるか確認する。無効化できれば生成する。できなければ Skill の配置を分離する方針を P0 決定記録に残す。いずれでも解消できない場合は `COLLISION` を報告し、opencode を `PARTIAL` とする（成功基準上は「明示した非フル」として扱う）。判定は `seh doctor --hosts` の静的 Discovery（各ホストの探索パス規則の実装）で行い、実機 Discovery は実 CLI 上限内で行える場合のみ。

### D6. 2件目 X 投稿由来の任意機能は除外
- 作らない: FR-046、テスト T16、`modules/reference-x/`、config `[optional] reference_2100854085104898216`、P0-05 の X 調査部分（P0-05 は Graphify 確定のみ）、P8-03、03 §6 プロファイル表 / §9 リスク表 / §11 トレーサビリティ / §12 v2.x 候補 / 02 §12 の該当行、01 §10。DoD の該当行も削除。
- FR-005（任意モジュール ON/OFF と残骸検出）の検証対象は `code-intelligence.graphify` と `memory.engram` とする。

### D7. ブランチ・コミット・push（開発プロセスのみ）
- 設計書のブランチ方針（`feature/v2-harness-core`・フェーズ別 PR）と `workflow.md` の PR フローは本件に限り適用しない。**main に直接コミット・push**。コミットは wave 単位、push はフェーズ完了時（CI PASS 確認後）。
- 製品側の Policy（02 §9「push/PR は外部作用として別途承認」）は変えない。`.github/pull_request_template.md` は残す。
- GitHub の branch protection / required checks の設定変更は行わない（外部設定）。そのため本リポジトリの Authoring Gate CI は「CI で FAIL を可視化」までで、強制力は `NOT_ENFORCED` と README / compatibility に明記する（04 §5.1）。

### D8. 配布
- `uv tool install git+https://github.com/jumtra/self-evolve-harness`。PyPI 公開・SDK extra は作らない。開発時は `uv tool install -e .` / `uv run seh`。
- CLI 未導入時の案内は Hook シム（D11）と `/harness-init` Skill が行う。`seh doctor` は導入済み `seh` と `.harness/generated.lock.json` の `seh_version` の不一致を検出する（メジャー不一致 = ERROR、マイナー不一致 = WARN）。

### D9. 設計書に無いローカル資産
- `desloppify` スキル: 削除（P8 最終 wave）。`.gitignore` の `.desloppify/` 行も削除。
- `doctor` スキルは v1 最終版（4c5ac19）で既に削除済み。`.claude/scripts/doctor.sh` を `seh doctor` に置換して削除（P8）。
- `harness-sync` スキル（4c5ac19 で追加）: `seh sync --hosts` に置換して削除（P8）。
- `.claude/skills/harness-init/memory-backends/`（file / engram 選択）: 知見を `providers/memory/` へ移し削除（P8）。
- `.agent-memory/`（v1 の file 記憶バックエンド、コミット共有）: **KEEP**（ユーザーデータ）。v2 の `memory.provider = "file"` は既定の保存先を `.agent-memory/` とし、v1 の記憶形式（`<type>_<slug>.md` + `MEMORY.md` 索引 + `metadata.evolve`）を読み書きできること（FR-040: 既存知識を消さない）。
- `.agents/`（未追跡・`skills → ../.claude/skills` シンボリックリンク）: P8 の dogfooding で **seh 管理の4ホスト生成物に置換**する（D12 の承認付き置換経路・snapshot あり）。P0〜P7 は触らない。

### D10. 外部ツール
- 新たな外部ツールを導入しない。Graphify Adapter は公式資料で確認した CLI 契約で実装し fake でテスト、実スモークは optional ジョブで skip 明示。
- CodeGraph は既存バイナリ（v1.4.1）で実スモーク（HOME を一時ディレクトリにして実行）。
- Engram は MemoryProvider の実スモークでは接続モックのみ（実 `~/.engram` を触らない）。

### D11. Hook の失敗時挙動
- Hook は `seh hook <event>` に集約し、生成物は薄いシム経由で呼ぶ。
- `seh` が PATH に**無い**場合のみ fail-open（警告して通過、SessionStart で導入案内を1回）。この劣化は compatibility report に明記。
- `seh` がある場合の malformed JSON・未捕捉例外・未知イベントは、PreToolUse 系では **exit 2（ブロック）**で fail-closed。それ以外のイベントは警告して通過。
- ホスト別のブロック手段（P0 で実仕様を確認し、確認できなければ `CI_ONLY`）:

  | Host | 事前防御の手段 | 確認不能時 |
  |---|---|---|
  | Claude | `.claude/settings.json` の command hook → `seh hook`（exit 2） | — |
  | AGY | `.agents/hooks.json` → `seh hook` | `CI_ONLY` |
  | Codex | 対象版の hook 機構（あれば） | `CI_ONLY` |
  | OpenCode | `.opencode/plugins/seh-guard.ts`（`seh hook` を呼び、非0なら throw） | `CI_ONLY` |

- OpenCode プラグイン（TypeScript）の検証は生成物のスナップショットテストに限る（bun/node 実行テストはしない）。

### D12. v1 → v2 移行の分類規則（FR-007/008/009）
- 判定対象は v1 既知パス一覧（`v1-baseline` に存在した `.claude/**`、`CLAUDE.md`、`AGENTS.md`、`.github/pull_request_template.md`）。
- `v1-baseline` の内容を base とした三者差分で分類:
  - 現物 == base → `REWRITE` / `DELETE`（計画どおり）
  - 現物 != base（プレースホルダ埋め込み・手編集を含む）→ `USER_OWNED_CONFLICT`。**明示承認がある場合のみ** snapshot 取得後に置換。承認なしは不変。
  - v1 既知パス外 → `KEEP`（ユーザー所有）
- シンボリックリンクは realpath で解決し、リンク経由で別の管理対象へ書き込む計画は `CONFLICT` として拒否する。置換する場合はリンク自体を snapshot・削除・再生成する。
- 個別ルール（ホスト生成先に既存物がある場合）: 生成先パス（`.agents/skills`、`.agents/rules`、`.agents/hooks.json`、`.opencode/`、`.codex/`）に既存物があれば、v1 既知パス外でも `USER_OWNED_CONFLICT` として計画に列挙し、承認付きで置換可能とする。`.agents/skills.json` は生成対象外なので `KEEP`。生成した `.agents/` 配下はコミット対象。
- 本リポジトリの dogfooding（D13）はこの「承認付き置換」経路で行う。

### D13. dogfooding（P8）
- **計画済みの停止点**: dogfooding apply は CLAUDE.md・Hook・Agent 権限を含む high_risk 変更（04 §4）であり、AI は承認を自己発行できない（01 §11、02 §10）。自律実行は `seh init --hosts all --plan` の差分・snapshot・rollback 手順を提示して**停止**し、ユーザーが対話で `seh init --apply` を実行する。apply 後の証拠収集から自律実行を再開する。
- `.harness/config.toml`: `hosts.enabled = ["claude","antigravity","codex","opencode"]`、`authoring.required_hosts = ["claude","codex","opencode"]`（AGY は `UNVERIFIED`）、`memory.provider = "engram"`、`code_intelligence.provider = "codegraph"`、`runtime.mode = "native"`、`hosts.antigravity.managed_cli = "disabled"`。
- **初回導入と Authoring Gate**: `seh init --apply` による初回生成は「導入」として所有権 Gate・承認 Gate のみを通す（baseline は `NOT_RUN` を許容）。Authoring Gate（`seh author promote` 経由の昇格条件）は導入**後**の正本変更から適用する。
- dogfooding 前に `uv tool install -e .` を実行する。`seh` が壊れて fail-closed で全ツールがブロックされた場合の復旧手順（ターミナルから `seh migrate rollback <snapshot>`、または `git checkout v1-baseline -- .claude CLAUDE.md AGENTS.md`）を README に記載する。
- 「動作する」証拠: (1) `seh doctor --hosts all` PASS、(2) stdin JSON で `seh hook <event>` を直接呼ぶ結合テスト PASS、(3) 参照監査 0、(4) `seh doctor --hosts all` による重複 Skill Discovery 0、(5) 生成 Skill の Authoring Eval（claude / codex / opencode の fresh session・実スモーク枠内）。不可なら `BLOCKED_NO_EVAL` として正直に報告。
- 新セッションでの Hook 実機確認はユーザー向け手順として完了報告に記す（同一セッションでは Hook 設定が固定のため）。
- `seh migrate rollback` で v1 状態に戻せることをテスト（一時 clone 上）で確認する。

### D14. 参照監査の除外パス
`docs/design/`、`docs/specs/`、`docs/decisions/`、`docs/v1-inventory.md`、`docs/baseline/`、`.agent-memory/`、`docs/migration-v1-to-v2.md`、`CHANGELOG.md`（リリースノート）、`src/seh/migration/`（v1 既知パス一覧）、`tests/fixtures/`（v1 サンプル）、`.harness/backups/`、git 履歴。それ以外での削除済み Skill/Agent/Rule 名の参照を 0 にする。

### D14a. P8 後の v1 残骸
- `.claude/.gitignore`: REWRITE（v2 生成物として `harness-log` 系・`worktrees/`・`settings.local.json` を除外）。
- `.claude/harness-log.jsonl`: 削除（v2 は `.harness/artifacts/` の JSONL trace）。gitignore 済みのため snapshot のみ。
- `.claude/worktrees/`: KEEP（gitignore 済み、Claude Code の作業領域）。
- `.claude/settings.local.json`: KEEP（ユーザー所有・不変）。

### D15. 開発中の v1 Hook との共存
- ファイル名に `secret` / `credential` / `.pem` / `.key` / `.env` を使わない（例: `redaction.py`、`masking`）。
- ダミー秘密値はテスト内で文字列連結により組み立て、リテラルを差分に残さない（例: `"sk-ant-" + "a" * 40`）。
- `rm -rf /<絶対パス>` は v1 の破壊コマンド Hook に誤検出されるため、削除は相対パスか Python の `shutil` で行う。
- P0〜P8 の間、AUTO-EVOLVE 通知が出ても evolver を起動しない（フィードバックの Engram 保存は継続）。

### D16. テスト Fixture の隔離
- `tests/fixtures/` 配下のサンプルプロジェクト・悪意ある文書は pytest `testpaths` / `norecursedirs`、ruff `extend-exclude`、pyright `exclude` で収集対象外にする。
- Claude Code 等が自動ロードするファイル名（`CLAUDE.md`、`AGENTS.md`、`GEMINI.md`、`SKILL.md`、`settings.json`、`hooks.json`）は `.fixture` サフィックス付きで保存し、テスト実行時に一時ディレクトリへ展開する（開発セッションへの注入防止）。
- テストは HOME・XDG 系を一時ディレクトリにし、`~/.claude.json`・`~/.engram`・各 CLI の設定を汚さない。GitHub Actions の git は `GIT_AUTHOR_*` / `GIT_COMMITTER_*` 環境変数で設定する。
- DAMP 境界: 一時 git リポジトリ・一時 HOME の作成は外部リソース管理として共有 fixture 可。mock CLI の出力（JSON/JSONL）・期待値はテスト内にインラインで書く。

### D17. ドキュメント更新
- README・`.claude/_reference.md`（P8 で `docs/architecture.md` へ統合可）の「CodeGraph 必須」「`.claude/` コピー導入」等の v1 記述を v2 に更新。README / Help / `seh doctor` / compatibility に「Core SDK 不要・AGY 制限・ホスト差・Native の NOT_ENFORCED」を表示（FR-100）。
- サンプルプロジェクトは Python / TypeScript の2種（C# は v2.x）。

### D18. 自律実行時の判断
- 実装中（フェーズ3）はユーザーに質問しない。判断に迷ったら安全側（生成しない・BLOCK・UNVERIFIED）を選び、決定記録と完了報告に記す。

## 制約

- 設計書 01 §13「対象外」と 02 §8 NFR（NFR-013〜015 含む）をそのまま適用する。
- 自己進化・承認ポリシー・信頼境界は AI が自己変更できない（01 §11）。
- テストは `.claude/rules/testing.md` の DAMP 厳守（D16 の境界）に従う。
- 本リポジトリの開発記憶は Engram を使い続ける。

## やらないこと

- 2件目 X 投稿由来の機能・スロット（D6）
- FR-026 stop sequence API Adapter、SDK アダプター実装（D1）
- PyPI 公開・Release 自動化、GitHub branch protection 設定（D7・D8）
- モデル呼び出しを伴う実測ベースライン・V0〜V5 実比較（D4）
- AGY の実 CLI 実行（D4）
- 外部ツールの新規インストール（D10）
- フェーズ別ブランチ・PR 作成（D7）
- C# サンプルプロジェクト（D17）

## エッジケース

- **実 CLI 未認証 / 版非互換**: `BLOCKED_AUTH` / `UNSUPPORTED` として報告し、該当ホストを FULL にしない。mock の結果で代替表示しない。
- **公式仕様が確認できないホスト機能**: 生成せず `UNVERIFIED` / `UNSUPPORTED`。
- **Graphify の正式リポジトリを確定できない**: Adapter は残し healthcheck が `ERROR` + 導入案内。決定記録に「未確定」。
- **v1 削除でこのセッションの手順書が消える**: 削除は P8 最終 wave のみ。implementer / reviewer / fixer は v2 でも残るためディスパッチは継続可能。
- **dogfooding apply で v1 実体と競合**: D12 の承認付き置換。承認はユーザーの対話 apply（D13 停止点）で行う。snapshot から rollback 可能。
- **Authoring Gate が自分自身の生成物をブロック**: 初回導入は Authoring Gate 対象外（D13）。導入後の `/work` Authoring Eval が実 CLI 上限内で回せなければ `BLOCKED_NO_EVAL` / `NOT_RUN` を記録し、Gate を暗黙 skip しない（完了報告で明示）。
- **CI が5回のループで通らない／同一エラー2回**: `workflow.md` どおり fixer へ委譲、3ストライク超過でエスカレーション。

### D19. 承認方式（実装中に確定）
- 承認が必要な適用（R2 / 保護パス / USER_OWNED_CONFLICT の置換 / migrate apply）は、**対話モード（stdin が TTY）の確認プロンプトで y の場合のみ**実行する。非対話では拒否して対話での再実行を案内する。
- 承認トークン発行 CLI は v2.0 では提供しない（`ApprovalToken` 契約と `Policy.authorize` の検証ロジックは将来のために維持）。
