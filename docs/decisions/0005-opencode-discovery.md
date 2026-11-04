# ADR-0005: 4ホスト共存時の Skill 探索と重複防止

- 状態: 採用（2026-11-04）。要件 D5 の「4ホスト共存の重複 Discovery」を具体化する。

## 事実

| Host | project の探索パス |
|---|---|
| Claude | `.claude/skills/` のみ（`.agents/skills` を読む根拠は無い） |
| Codex | `.agents/skills`（cwd から repo ルートまで遡る）。同名の Skill があると両方が選択肢に出る |
| AGY | `.agents/skills`（親ディレクトリも含む）。旧形式の `.agent/skills` も読む |
| OpenCode | `.opencode/skills`、`.claude/skills`、`.agents/skills` の3つ。同名の Skill があった場合の挙動は未定義（UNVERIFIED） |

OpenCode の探索パスを抑止する手段は環境変数だけで、設定キーは無い。

| 環境変数 | 効果 |
|---|---|
| `OPENCODE_DISABLE_CLAUDE_CODE_SKILLS=1` | `.claude/skills` だけを無効化 |
| `OPENCODE_DISABLE_EXTERNAL_SKILLS` | `.claude` と `.agents` の両方を無効化 |

## 決定

1. **配置**
   - 論理 Skill の実体は `.agents/skills/<id>/` に1つだけ置く（Codex / AGY / OpenCode 用）。
   - Claude 用に `.claude/skills/<id>/` を生成する。
   - OpenCode 用の `.opencode/skills` は生成しない。
2. **OpenCode の重複**
   - OpenCode からは `.claude/skills/<id>` と `.agents/skills/<id>` の両方が見え、同じ名前が2つになる。
   - **Managed 実行時**: Runner が `OPENCODE_DISABLE_CLAUDE_CODE_SKILLS=1` を env に渡して抑止する。
   - **Native 利用時**: 抑止する手段が無い。`seh doctor --hosts` で `COLLISION`（opencode、名前は `work` / `harness-init`）を報告し、opencode の compatibility を **PARTIAL** とする。あわせて、利用者向けにシェルでこの環境変数を設定するよう案内する。
   - 2つの内容は同じ正本から生成し、hash が一致することを検査する。そのため実害は「同じ Skill が2つ見える」ことに限られる。ただし、同名時の挙動が未定義なので PASS とは扱わない。
3. **判定方法**: `seh doctor --hosts` は、各ホストの探索パス規則（本 ADR の表）を実装した静的 Discovery で判定する。実機での Discovery は、実 CLI の利用上限（D4）の範囲内で可能な場合だけ行う。
4. Codex で同名 Skill の重複が起きないよう、`.agents/skills` 以外の場所に同名の Skill を生成しない。

## 出典
- https://docs.opencode.ai/docs/skills/
- https://docs.opencode.ai/docs/rules/
- https://opencode.ai/docs/cli/
- https://learn.chatgpt.com/docs/build-skills
- https://antigravity.google/docs/skills
- https://code.claude.com/docs/en/skills
- https://github.com/anomalyco/opencode/issues/14506
