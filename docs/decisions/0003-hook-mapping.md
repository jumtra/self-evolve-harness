# ADR-0003: ホスト別 Hook（事前防御）の写像

- 状態: 採用（2026-11-04）。要件 D11 の表を本 ADR で確定・修正する。

## 決定

| Host | 事前防御の手段 | ブロックの仕方 | 能力 |
|---|---|---|---|
| Claude | `.claude/settings.json` の `hooks.PreToolUse` に command handler を置き、シム経由で `seh hook <event>` を呼ぶ | **exit 2**（stderr に理由を出す）。exit 1 などの非 0 はブロックにならない。v2.1.295 以降は `onFailure: "block"` も併用する | NATIVE |
| Codex | `.codex/hooks.json` の `PreToolUse` | exit 2 と stderr。ただし**レビューして trust するまで実行されない**（hook の hash に紐づく）。project の `.codex/` も trusted でないと読まれない | ADAPTED（実効性は UNVERIFIED）。補完として `.codex/rules/*.rules` の `forbidden` と CI を併用する |
| OpenCode | `.opencode/plugins/seh-guard.ts` の `tool.execute.before` で `seh hook` を呼び、非 0 なら `throw` | `throw new Error(...)`（公式の例） | NATIVE。subagent への効き方は UNVERIFIED。`--pure` / `OPENCODE_PURE` を付けると無効になる |
| AGY | `.agents/hooks.json` の `PreToolUse` | stdout の JSON に `{"decision":"deny"}` を出す（stdin は camelCase の JSON） | ADAPTED（実効性と headless 動作は UNVERIFIED）。必須ゲートは CI に置く |

### `seh hook` の契約
- `seh hook <event> --host <claude|codex|opencode|antigravity>` が、ホストごとの入出力形式を正規化して吸収する。
  - stdin の JSON 形式（snake_case / camelCase）の違いを吸収する。
  - ブロックの表現を出し分ける。Claude と Codex は exit 2、AGY は stdout に deny の JSON、OpenCode は exit 2 を plugin が throw に変換する。
- D11 の fail-closed 規約は変えない。`seh` があるときは、PreToolUse の malformed JSON、未知のイベント、未捕捉の例外をすべてブロックとして扱う。`seh` が無いときだけ、シムが警告を出して通過させる（fail-open）。
- Managed 実行中の注意:
  - Claude で `--bare` を付けると Hook が無効になる。
  - OpenCode で `--pure` を付けると plugin が無効になる。
  - この2つを使った実行は `RunContext` に「hook 無効」と記録する。
- 要件 D11 の表で「Codex = CI_ONLY」としていた行は、本 ADR で **ADAPTED** に修正する（Hook 機構が存在するため）。

## 出典
- https://code.claude.com/docs/en/hooks
- https://learn.chatgpt.com/docs/hooks
- https://docs.opencode.ai/docs/plugins/
- https://antigravity.google/docs/hooks

## 既知の制約（P1 レビュー後に追記）
- commit 前秘密スキャンは `git diff --cached` / `git diff HEAD`（`-a`・同一コマンド内 `git add` 時）を走査する。`git add . && git commit` で**新規の未追跡ファイル**に含まれる秘密は検出できない（`git diff` は untracked を見ない）。最終防御は CI のシークレットスキャン（FR-079）とする。
- Hook は Native の早期検出であり安全境界の唯一の手段ではない（01 §4）。非対話実行は `--unattended` / `SEH_UNATTENDED=1` で ASK を DENY に倒す。
