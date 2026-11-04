# ADR-0001: ホストごとの生成形式

- 状態: 採用（2026-11-04）
- 確認した版: claude 2.1.318 / codex 0.166.0 / opencode 1.19.5 / agy 1.4.12
- 根拠: 公式ドキュメント（末尾）と各 CLI の `--help`。食い違う場合は `--help` を正とした。

## 決定

### 1. 常時指示ファイル

| Host | 生成先 | 根拠となる挙動 |
|---|---|---|
| Claude | `CLAUDE.md`（生成ブロック）。先頭に `@AGENTS.md` を置き、共通部分を import する | `CLAUDE.md` があると `AGENTS.md` を読まない（v2.1.277 以降）。`@` で import できる |
| Codex | `AGENTS.md`（生成ブロック） | 階層ごとに `AGENTS.override.md` > `AGENTS.md` の順で1つを採用する。既定の上限は 32KiB |
| OpenCode | `AGENTS.md` | `AGENTS.md` を優先し、無ければ `CLAUDE.md`（先に見つかった方だけ） |
| AGY | `AGENTS.md` | `AGENTS.md` / `GEMINI.md` を累積して読む。両者の優先順位は未定義なので、`GEMINI.md` は生成しない |

`HostAdapter.lint` は「`CLAUDE.md` があるのに `@AGENTS.md` を import しておらず、共通方針が Claude に届かない」状態を検出する。

### 2. Skill

- 実体は `.agents/skills/<id>/SKILL.md` に1つ置く（Codex / AGY / OpenCode が共通で読む）。
- Claude 用には `.claude/skills/<id>/SKILL.md` を別途生成する。Claude が `.agents/skills` を読む根拠が公式資料に無いため。
- 共有パスに置く SKILL.md の frontmatter は最小形とし、`name` と `description` だけにする。
  - `name` は OpenCode の正規表現 `^[a-z0-9]+(-[a-z0-9]+)*$` に合わせ、1〜64文字でディレクトリ名と一致させる。
  - `description` は 1〜1024 文字。
- Claude 固有のキー（`allowed-tools`、`disable-model-invocation`、`when_to_use`、`argument-hint` など）は `.claude/skills` の出力にだけ付ける（FR-064）。
- Codex 固有の設定は `agents/openai.yaml`。v2.0 では生成しない（必要になった時点で ADAPTED として追加する）。
- 4ホスト共存時の重複探索の扱いは ADR-0005 で決める。

### 3. Rules（path-scoped）

| Host | 形式 |
|---|---|
| Claude | `.claude/rules/*.md`。frontmatter は `paths:` だけが意味を持つ。`paths` が無い rule は常時ロードされる |
| AGY | `.agents/rules/*.md`（直下のみ）。frontmatter の `trigger` が必須（`always_on` / `model_decision` / `glob` / `manual`）。`glob` なら `globs`、`model_decision` なら `description` も必須。無効な rule は黙って捨てられるため、lint で必須チェックする。1ファイル 24,000 バイトが上限 |
| Codex | path-scoped な指示の仕組みが無い。共通方針は `AGENTS.md` に、局所的なルールは CI でのみ担保する（`CI_ONLY`） |
| OpenCode | path-scoped な指示の仕組みは未確認。`opencode.json` の `instructions` に glob を追加する方式で `ADAPTED`（UNVERIFIED） |

### 4. Subagent（論理 4 Agent: implementer / reviewer / fixer / evolver）

| Host | 生成先と形式 | read-only の表現 | 能力 |
|---|---|---|---|
| Claude | `.claude/agents/<name>.md`。必須 `name` と `description`、任意で `tools`、`model`、`effort` | `tools: Read, Grep, Glob` の allowlist（Bash を含めない） | NATIVE |
| Codex | `.codex/agents/<name>.toml`。必須 `name`、`description`、`developer_instructions` | agent 単位では強制できない（`sandbox_mode` は agent ファイルでは無効なので生成しない）。指示文と、Managed 実行時の `--sandbox read-only`、CI で担保する | ADAPTED |
| OpenCode | `.opencode/agents/<name>.md`。`description` と `mode: subagent`、`permission` | `permission: {edit: deny, bash: deny}` | NATIVE |
| AGY | `.agents/agents/<name>.md`。必須 `name` と `description`、任意で `tools`、`model`、`commandExecutionPolicy` | `tools` から書き込み系を除外する。マップされていない tool 名でハングする既知の不具合がある | UNVERIFIED |

### 5. 権限

| Host | 権限の置き場所 |
|---|---|
| Claude | `.claude/settings.json` の `permissions` と agent の `tools` |
| OpenCode | `permission`（`allow` / `ask` / `deny`。最後に一致した規則が勝つ） |
| AGY | プロジェクト単位の設定ファイルの所在が未確認。ユーザー設定（`~/.gemini/...`）には書き込まない（FR-080: 生成できない deny を黙って allow 扱いにしない → `UNSUPPORTED` と報告） |
| Codex | `.codex/rules/*.rules`（Starlark の `prefix_rule`、`forbidden`）で危険コマンドを拒否する。project の `.codex/` は trusted のときだけ有効なので `ADAPTED` |

## 未確認（実装は UNVERIFIED として扱う）

- 4ホスト間の tool 名の対応表
- OpenCode で path-scoped な指示を実現する方法
- AGY における `GEMINI.md` と `AGENTS.md` の優先順位
- AGY のプロジェクト単位の権限設定

## 出典

- https://code.claude.com/docs/en/skills
- https://code.claude.com/docs/en/sub-agents
- https://code.claude.com/docs/en/memory
- https://learn.chatgpt.com/docs/agent-configuration/agents-md
- https://learn.chatgpt.com/docs/agent-configuration/subagents
- https://learn.chatgpt.com/docs/agent-configuration/rules
- https://learn.chatgpt.com/docs/build-skills
- https://antigravity.google/docs/skills
- https://antigravity.google/docs/rules
- https://antigravity.google/docs/subagents
- https://antigravity.google/docs/permissions
- https://docs.opencode.ai/docs/skills/
- https://docs.opencode.ai/docs/rules/
- https://docs.opencode.ai/docs/agents/
- https://docs.opencode.ai/docs/permissions/
