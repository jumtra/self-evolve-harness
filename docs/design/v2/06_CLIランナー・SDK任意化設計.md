# self-evolve-harness v2.0 CLIランナー・SDK任意化設計書

- 文書ID: SEH2-RUNTIME-CLI-001
- バージョン: 1.3（2026-11-04／未実装）
- 適用対象: Claude Code / Codex / OpenCode / Google Antigravity（AGY）
- 位置づけ: `01`〜`05`の実行基盤を**SDK不要なCLI First**へ変更するための実装契約

## 1. 決定事項

**Python/TypeScriptのAgent SDKパッケージは必須ではない。初期構成には導入しない。** 公式CLIでモデル内部のエージェントループを実行し、Pythonの外側からDAG、進捗、worktree、独立評価、再試行を管理する。

```text
User or Host-native /work
          |
  CanonicalSpec / TaskSpec / Policy  (.harness/)
          |
    WorkflowEngine (Python)
    |  DAG / budgets / checkpoints / isolated worktrees
    +---------+---------+
    |                   |
CliAgentRunner        Deterministic Tool Nodes
    |                   |  tests, schema, diff, policy
    +--- Host CLI -------+
           |
  Claude -p | codex exec | opencode run | AGY policy-gated
           |
  Normalized RunResult + independent VerificationGate
           |
  Promote / Repair (max attempts) / Stop / Human Approval
```

別物として扱う3層:

1. `HostAdapter`: 共通Skill/Rule/Promptから各製品用ファイルを生成。CLI実行はしない。
2. `CliAgentRunner`: 許可済みホストCLIを安全なsubprocessとして起動し、結果とイベントを正規化する。プロンプトの最終的な品質は判定しない。
3. `VerificationGate`: 取得したdiff・テスト・Schema・許可・評価証拠で採否を決定。**LLMの自己評価に依存しない**。

## 2. 互換性／利用条件

| 項目 | Claude Code | Codex | OpenCode | AGY |
|---|---|---|---|---|
| CLI入口 | `claude -p` | `codex exec` | `opencode run` | `agy -p` |
| 機械可読な出力 | `--output-format json/stream-json` | `--json`（JSONL） | `--format json` | `--output-format json/stream-json` |
| 最終Schema制約 | CLI実機probeに従う | `--output-schema <file>` | 共通Harness validatorで保証 | `--json-schema <schema>` |
| ホスト内の権限制御 | CLIのtool allowlist等 | `--sandbox`/execpolicy | permissions/agent設定 | permissions設定（ヘッドレスsoft-denyあり） |
| Managed初期実行 | 対応候補 | 対応候補 | 対応候補 | **既定POLICY_BLOCKED** |
| Skill/Rule生成 | 対応予定 | 対応予定 | 対応予定 | 対応予定（別契約） |

**AGYの重要な制約**: Google公式FAQは個人向けプランで、`agy -p`を第三者のコーディングエージェントやアプリでラップする利用をサポートしないと明記。CLI自体にヘッドレス機能が存在することは、すべての外部ハーネス利用を許可することを意味しない。`seh`は`antigravity.managed_cli=disabled`を既定とし、利用者の契約/許可が明示的に確認できなければ実行せず`POLICY_BLOCKED`。外部ツールから個人アカウントを迂回利用したりアカウントローテーションする実装は作らない。

**Claudeの語義注意**: 公式説明では`claude -p`が「Agent SDKのCLI」と紹介されるが、これはPython/TS Agent SDKパッケージを追加する必要があるという意味ではない。本設計のSDK不要は、**CLIとは別のライブラリ追加が不要**という意味。

## 3. 設定モデル（提案）

```toml
[hosts]
enabled = ["claude", "codex", "opencode", "antigravity"]

[runtime]
mode = "native"                  # native | managed
backend = "cli"                  # v2.0唯一の標準Managed backend
selected_host = "claude"         # managedで明示指定（auto選択時も選択結果を記録）
max_parallel = 2
max_attempts_per_unit = 3
max_seconds_per_unit = 600
max_total_seconds = 3600

[runtime.security]
require_worktree = true
command_allowlist = ["git", "python", "pytest"]
allow_network = false
trust_external_repo = false

[hosts.antigravity]
surface = "auto"
managed_cli = "disabled"         # 設定/Skill配布のみが既定
# enabledは十分な利用許諾・契約確認を済ませた環境でのみ選択可能

[sdk]
enabled = false                  # 将来の任意プラグイン候補、初期実装なし

[authoring]
policy = "required"
require_eval_for_behavior_change = true
required_hosts = "active"         # 必要なホストを明示。全ホストFULL主張には全て実機PASSが必要
require_ci_for_promote = true
```

`command_allowlist`はHarness管理の決定論的ツールノード用の例であり、**エージェントCLI内部のコマンドを完全に制御できる保証ではない**。OS/sandbox/host permissions/CIを別途必須とする。

## 4. CLI Runnerの最低契約

```python
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Protocol

class TerminalState(StrEnum):
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    BLOCKED_AUTH = "BLOCKED_AUTH"
    POLICY_BLOCKED = "POLICY_BLOCKED"
    UNSUPPORTED = "UNSUPPORTED"
    INVALID_OUTPUT = "INVALID_OUTPUT"
    TIMED_OUT = "TIMED_OUT"
    CANCELLED = "CANCELLED"

@dataclass(frozen=True)
class RunContext:
    worktree: Path
    cwd: Path
    deadline_seconds: int
    env_allowlist: tuple[str, ...]
    session_policy: str
    permissions_profile: str

@dataclass(frozen=True)
class RunResult:
    run_id: str
    host: str
    terminal_state: TerminalState
    exit_code: int | None
    final_response: str | None
    event_log_digest: str | None
    evidence_refs: tuple[str, ...]
    usage: dict | None             # unknownとゼロを区別
    error_code: str | None

class CliAgentRunner(Protocol):
    def probe(self) -> dict: ...    # CLI版、auth、json、sandbox、session resume等
    async def run_once(self, prompt: str, context: RunContext) -> RunResult: ...
    async def cancel(self, run_id: str) -> None: ...
```

内部のVendor Adapterは`build_argv()`, `parse_event()`, `detect_terminal_status()`, `normalize_usage()`を実装する。共通Coreに`--json`などのベンダー特有のフラグは書かない。`session.resume`・`stream`・`tool.before_call`は別々のCapabilityとして宣言し、サポートされない機能を「一応動いた」で代替しない。

## 5. CLIプロセスの実行規約

1. `probe()`で`which`、版、認証、ライセンス/利用資格、利用可能なflags、対象Hostのconfig権限を確認。`doctor`のレポートに記録する。
2. 入力に含まれる任意文字列をshellへ埋め込まず、`subprocess`の**argv配列**とstdinで渡す。任意の`bash -lc`でPromptを組み立てない。
3. 編集作業はユニット専用Git worktreeと一時HOME/config領域で隔離し、実行プロセスのcwdをworktreeへ限定。ネットワーク・シークレットアクセスは既定deny。
4. `stdout`と`stderr`を別にキャプチャし、出力上限、タイムアウト、強制停止を設定。再実行で前試行の子プロセスを放置しない。
5. JSON/NDJSONを正確にパース。途中打ち切り、未知の終端、認証失敗、権限拒否、ホスト版非互換は`FAILED/BLOCKED`として扱う。
6. `exit_code=0`でもタスク完了とみなさず、必要な差分・コードテスト・Schema・安全チェックと`FinalStatus`を検証する。ホストが権限をsoft-denyした場合の見落としを防ぐ。
7. `RunResult`は構造化結果と参照のみ永続化。stdout全量・ユーザー入力・秘密情報は既定で収集せず、必要なログはマスキング＋保持期限を適用。
8. 1ユニット失敗なら`Verdict`の具体的な失敗証拠を次試行へ返す。試行上限（標準3）到達で停止し、成功済みユニットを再実行しない。

`CLI runner`による保護範囲は**ユニット間の状態遷移と成果物の採否**であり、モデル内の個々のTool呼出し全体を注入可能にすることではない。ツール単位の介入が必須になった場合のみ任意SDK/Pluginの費用対効果と権限を評価する。

## 6. 公式CLIの引数生成（概念例）

```python
# 各ホストに存在する引数のみ使う。以下はargvを組み立てる例で、未実装。
def build_argv(host: str, prompt: str) -> list[str]:
    if host == "claude":
        return ["claude", "-p", prompt, "--output-format", "stream-json"]
    if host == "codex":
        return ["codex", "exec", "--json", prompt]
    if host == "opencode":
        return ["opencode", "run", "--format", "json", prompt]
    if host == "antigravity":
        # policy authorization must occur before reaching here
        return ["agy", "-p", prompt, "--output-format", "stream-json"]
    raise ValueError("UNSUPPORTED_HOST")
```

実装では大きい/機密PromptをCLI引数に含めずstdinやワークスペース上の限定参照を選択する。上記argv例は仕様上の最小形を示すだけであり、特にAGYについて**利用資格の確認なしに実行可能とするものではない**。プロセス起動は`asyncio.create_subprocess_exec(*argv, cwd=..., env=..., start_new_session=True)`等を利用し、OS差分はシステム層で吸収する。

**ログの注意**: `stdout`にはモデル応答や内部Toolイベントが含まれ得る。Events全量をCI artifactとして公開しない。機密消去とダイジェスト参照を標準にする。

## 7. ManagedのGenerate → Evaluate → Repair

```python
async def execute_unit(unit, runner, checker, limit=3):
    feedback = None
    for attempt in range(1, limit + 1):
        prompt = compose_prompt(unit, feedback)  # 細部はPrompt Registryが管理
        run = await runner.run_once(prompt, isolated_context(unit, attempt))
        if run.terminal_state != TerminalState.SUCCESS:
            return UnitResult.blocked_or_failed(run)
        verdict = await checker.evaluate(unit, run)  # 生成者と独立
        persist_evidence(unit.id, attempt, run, verdict)
        if verdict.passed:
            return UnitResult.passed(verdict)
        feedback = verdict.as_repair_input()
    return UnitResult.failed("MAX_ATTEMPTS_REACHED")
```

モデル内部のTool計算を置き換える必要があるときは、ハーネス側で**決定論的Code Nodeをワークフローに挿入**する。動画の日割りツールのようなPython計算はCLI中にツール呼び出しを横取りしなくても、明示的なノードで呼んで出力を次Agentユニットへ渡せる。ただし**任意のモデル内計算が必ずこのノードを通るとは保証しない**。必要な検証結果はFinal Gateで担保する。

## 8. 実装対象・非対象

**実装する**:

- `src/seh/runtime/runners/base.py`、`claude_cli.py`、`codex_cli.py`、`opencode_cli.py`、`antigravity_cli.py`（AGYはPolicy Gateが先）
- `src/seh/runtime/process.py`: subprocess起動・stream parser・process group timeout/cancel
- `src/seh/runtime/cli_capability.py`: flags/認証/ライセンス許可・構造化出力の確認
- `src/seh/runtime/scheduler.py`, `repair.py`, `worktree.py`, `checkpoint.py`
- `tests/unit/cli_runners/`, `tests/integration/cli_runners/`, `tests/e2e/managed/`

**初期版には実装しない**:

- `claude-agent-sdk`/`@openai/codex-sdk`などSDK依存の常駐Agentプロセス
- SDK専用の`send()/stream()`必須インターフェース（CLIにはone-shotが適している）
- 低レベルモデルAPIの完全自作Toolループ、Tool実行直前のすべてのコールバック仲介
- 利用条件に反するAGYの外部ラッピングや認証情報の流用

## 9. テスト・受け入れ基準

| テストID | ケース | 期待結果 |
|---|---|---|
| CLI-001 | SDKをインストールしていないPythonクリーン環境 | `seh --help`, `seh init --plan`, Mock Managedが稼働 |
| CLI-002 | Claude正常JSON/JSONL・非正常JSON | 終端イベント必須。不正は`INVALID_OUTPUT` |
| CLI-003 | Codex `codex exec --json`・schema出力 | 異なるイベントを共通`RunResult`へ変換 |
| CLI-004 | OpenCode `opencode run --format json` | イベント解析と最終checkが動作 |
| CLI-005 | AGYの利用条件未確認 | Runnerが起動せず`POLICY_BLOCKED`。設定生成は可 |
| CLI-006 | 子プロセス異常終了 / stdout途切れ / stderrに権限拒否 | PASS禁止。理由コード・証拠を保存 |
| CLI-007 | タイムアウト / キャンセル / process groupのkill | 残存プロセス0、二重昇格なし |
| CLI-008 | 4独立ノード中1失敗 | 当該ノードだけ最大3回Repair。他の成功ノードは再試行しない |
| CLI-009 | 書込み範囲外diff / 未許可Network/Secret | Gate FAIL。ホスト内Tool許可だけに依存しない |
| CLI-010 | Claude/AGY/Codex/OpenCodeのCapability差 | 互換性レポートに`FULL/PARTIAL/BLOCKED`の根拠あり |
| CLI-011 | 出力にusage/costが含まれない | 0を捏造せず`UNKNOWN`として記録 |
| CLI-012 | Tool内部に介入が必要な機能 | CLIでは`UNSUPPORTED`、SDKプラグインの有効化提案だけを提示 |

本設計の**実機テストは認証・契約・アクセス権を確認できるホストに限る**。CLIが入っていないCIではMock contract testのみの結果を公開し、4ホスト実機済みと表示しない。

## 10. 公式根拠・後から確認する箇所

- Claude Code CLI/headless: https://code.claude.com/docs/en/headless ; https://code.claude.com/docs/en/cli-reference
- Codex CLI/non-interactive: https://learn.chatgpt.com/docs/non-interactive-mode ; https://learn.chatgpt.com/docs/cli/reference
- OpenCode CLI: https://opencode.ai/docs/cli/
- AGY CLI headless: https://antigravity.google/docs/cli/headless/
- AGY consumer-plans FAQ: https://antigravity.google/docs/faq

実装時は各CLIの実際の`--help`、`--version`、権限設定と最小スモークで更新する。**「全ホストでSDKを使わずに同じ設定を生成できる」ことと「全ホストのManaged Agentが同条件で実行できる」ことは別の達成条件**として評価する。
