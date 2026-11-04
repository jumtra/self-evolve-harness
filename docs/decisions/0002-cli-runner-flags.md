# ADR-0002: CLI Runner のフラグと終端判定

- 状態: 採用（2026-11-04）
- 確認した版: claude 2.1.318 / codex 0.166.0 / opencode 1.19.5 / agy 1.4.12（`--help` の実測と公式ドキュメント）

## 決定（Runner ごとの argv と TerminalState への対応付け）

ベンダー固有のフラグとフィールドは `runtime/runners/<host>_cli.py` の中に閉じ込め、Core には持ち込まない。プロンプトは argv ではなく stdin で渡す（大きな入力や機密を含む入力への対策）。

### Claude（`claude -p`）
- argv の例: `claude -p --output-format stream-json --verbose --permission-prompts none [--json-schema <schema>] [--allowedTools ...]`。プロンプトは stdin で渡し、cwd は worktree にする。
- Eval では `--bare` を使わない。Skill と Rules を読み込ませる必要があり、`--bare` は Hook も読み込まないため。
- 終端イベントは `type == "result"`。
  - SUCCESS の条件: `subtype == "success"` かつ `is_error == false`。
  - `error_max_turns`、`error_max_budget_usd`、`error_during_execution`、`error_max_structured_output_retries` は FAILED とし、subtype を `error_code` に記録する。
  - `--json-schema` を指定したのに `structured_output` が無い場合は INVALID_OUTPUT。
- 権限拒否は `result.permission_denials`（`tool_name`, `tool_use_id`, `tool_input`）を evidence として記録する。拒否がある場合、exit 0 でも PASSED にしない（FR-091）。
- usage は `modelUsage` を正とする（subagent を含む）。`total_cost_usd` は推定値として記録する。
- 認証エラーは `system/api_retry` の `error` カテゴリ `authentication_failed`、または `result` のエラーで判定し、BLOCKED_AUTH とする。
- 終端イベントが無いまま EOF に達した場合は INVALID_OUTPUT。

### Codex（`codex exec`）
- argv の例: `codex exec --json -C <worktree> -s workspace-write [--output-schema <file>] --skip-git-repo-check -`。`-` を付けてプロンプトを stdin で渡す。
- `codex exec` には `-a` が無く、`-p` は profile 指定である点に注意。
- 終端イベントは `turn.completed` なら SUCCESS 候補、`turn.failed` と `error` なら FAILED。失敗時の payload 形式は公式資料に無いため、生イベントを evidence として保存する。
- usage は `usage.{input_tokens, cached_input_tokens, output_tokens, reasoning_output_tokens}`。コストは UNKNOWN とする（FR-095、CLI-011）。
- 認証エラーの判定は UNVERIFIED。非 0 終了かつ stderr の認証系パターンで BLOCKED_AUTH 候補とし、確定判定は実スモークで記録する。

### OpenCode（`opencode run`）
- argv の例: `opencode run --format json --dir <worktree> [--agent <name>]`。プロンプトは stdin で渡す。`-p` はパスワード指定であり、プロンプトではない点に注意。
- イベントのスキーマは **UNVERIFIED**（公式に記載が無く、第三者資料に基づく）。
  - 成功は `step_finish`。
  - 失敗は次のいずれか: `error` イベント、`tool_use.state.status == "error"`、`exit != 0`。
  - **exit 0 かつ stdout が空の場合は INVALID_OUTPUT**（auto-reject 後に空出力になる既知の不具合への対策）。
- 承認待ち（ask）でハングする既知の不具合があるため、タイムアウトとプロセスグループ kill を必須にする。`--auto` は worktree で隔離したうえで CI と併用する場合にだけ使う。
- JSON Schema を強制する手段が無いため、Harness 側の validator で検証する（T27）。
- usage は `step_finish.part.cost` と `tokens.*`（UNVERIFIED）。

### AGY（`agy -p`）
- 既定は `managed_cli = "disabled"` で `POLICY_BLOCKED` とし、**プロセスを起動しない**（ADR-0003 補足、FAQ）。
- 有効化された場合の argv（参考）: `agy -p --output-format stream-json [--json-schema ...]`。終端は `result.status`（`SUCCESS` / `ERROR` / `CANCELED` / `INTERRUPTED` / `INVALID` / `WAITING` / `RUNNING`）。SUCCESS 以外はすべて非 SUCCESS として扱う。
- 権限拒否は soft-deny で、実行が続く。stderr に出る通知を拒否として正規化する。
- 認証エラーは `authentication required` で非 0 終了になり、BLOCKED_AUTH とする。

### 共通
- `probe()` で確認するのは次の項目。`compatibility.json` と `generated.lock.json` にはコマンド名とバージョンだけを記録し、絶対パスは記録しない。
  - `shutil.which` によるコマンドの存在
  - `--version`
  - `--help` に必須フラグが含まれるか
- 子プロセスの env は allowlist で組み立て、`CLAUDECODE` と `CLAUDE_CODE_*` を除外する（入れ子起動を防ぐ）。
- セッション継続はオプションの Capability とする（Claude: `--resume`、Codex: `exec resume`、OpenCode: `-s`、AGY: `--conversation`）。Repair は常に fresh session で行えるようにする（FR-097）。

## 未確認
- Codex の `turn.failed` と `error` の payload、認証エラー時の終了コード
- OpenCode の `--format json` の公式スキーマと終了コード
- AGY の `--print-timeout` を超えたときの status

## 出典
- https://code.claude.com/docs/en/headless
- https://learn.chatgpt.com/docs/non-interactive-mode
- https://learn.chatgpt.com/docs/cli/reference
- https://opencode.ai/docs/cli/
- https://littlebearapps.com/help/untether/opencode-stream-json-cheatsheet/ （第三者）
- https://antigravity.google/docs/cli/headless/
