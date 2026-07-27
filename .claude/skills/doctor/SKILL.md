---
name: doctor
description: >
  ハーネス自己診断スキル。記憶層(Engram)・コードグラフ(CodeGraph)の到達性、
  settings の JSON 妥当性、ダングリング参照、デッドルールを検査し、修正案を提示する。
  環境が壊れている疑い・SessionStart の HARNESS警告・定期点検のときに使う。
---

# ハーネス自己診断

ハーネスの健全性を検査し、問題と**修正案**を報告する。
破壊的な自動修正はしない（提案に留め、適用はユーザー承認または明示指示のとき）。

## 手順

各項目を順に実行し、結果を ✅ / ⚠️ / ❌ で表にまとめる。証拠（コマンド出力）を添える。

### 1. 記憶層（Engram）

```bash
command -v engram >/dev/null 2>&1 && engram --version || echo "engram 未検出"
```

- 未検出 → ❌。`/harness-init` の必須ツール導入（Engram バイナリ配置 + `~/.claude.json` 登録）を案内
- MCP ツールがロード済みなら `mem_stats` / `mem_current_project` で応答と検出プロジェクトを確認
- **このプロジェクトの観測件数を確認**する。`mem_stats` の Projects に現在の
  プロジェクト名が無い、または `engram search "" --project <repo>` が 0 件なら ⚠️
  「記憶層は稼働しているがこのプロジェクトにはまだ何も保存されていない」と警告し、
  `memory.md` のフィードバック保存・`/save-session` が実際に走っているか点検を促す

### 2. コードグラフ（CodeGraph）

```bash
command -v codegraph >/dev/null 2>&1 && codegraph --version || echo "codegraph 未検出"
test -d .codegraph && echo ".codegraph あり" || echo ".codegraph なし（codegraph init 未実行）"
```

- 未検出 → ⚠️（domain.md 生成・調査に影響。`/harness-init` の導入手順を案内）

### 3. settings の JSON 妥当性

```bash
for f in .claude/settings.json .claude/settings.local.json; do
  [ -f "$f" ] && (python3 -m json.tool "$f" >/dev/null 2>&1 && echo "OK: $f" || echo "INVALID: $f")
done
```

- INVALID → ❌。壊れた settings.json は hooks を無効化する。該当箇所を特定して修正案を出す

### 4. ダングリング参照（実体の無い skill / agent 参照）

rules / skills / agents が参照する `/skill-name` や `subagent_type` のうち、
`.claude/skills/<name>/SKILL.md` / `.claude/agents/<name>.md` が実在しないものを検出:

```bash
# 参照されているスキル名を集め、実体の有無を照合
grep -rhoE '/[a-z][a-z0-9-]+' .claude/rules .claude/skills .claude/agents --include="*.md" \
  | sort -u > /tmp/doctor-refs.txt
# 各 /name について .claude/skills/name/ の存在を確認（手動照合でよい）
ls .claude/skills/ .claude/agents/
```

- 参照はあるが実体が無い → ⚠️。参照削除 or スキル作成をユーザーに選ばせる
  （過去に loop-protocol という参照だけ残り実体が無い問題が発生した）

**既知の偽陽性（報告しない）**:

| 検出される名前 | 理由 |
| -------------- | ---- |
| `/loop`, `/schedule`, `/init`, `/config`, `/doctor` 以外の組み込みコマンド | Claude Code 組み込み。`.claude/skills/` に実体が無いのが正常 |
| `/skill-name`, `/name` 等のプレースホルダ表記 | ドキュメント中の記法例（「`/skill-name` で手動呼び出し」） |
| `/harness-init` が生成すると明記されているもの | まだ生成前なら実体が無いのが正常 |

上記を除いた上で残ったものだけを ⚠️ として報告する。除外後にゼロなら ✅。

### 5. デッドルール軽スキャン

各 rules ファイルについて、`evolve-rules` の No-Op テスト基準
（`references/ahe-principles.md`）で「モデルのデフォルト動作と同じ＝不要」な行が
無いか軽く確認する。疑わしい行を ⚠️ で列挙（削除は evolve-rules または承認に委ねる）。

### 6. メモリ二重系統の確認

```bash
ls ~/.claude/projects/*/memory/ 2>/dev/null && echo "ファイルベース memory あり" || echo "ファイルベース memory なし"
find . -name "MEMORY.md" 2>/dev/null
```

- ファイルベース memory にファイルがある → ⚠️。`memory.md` は Engram を正とするため、
  旧ファイルの `memory.bak/` 退避を案内（`memory.md` の「既存 auto-memory の扱い」）

### 7. 実行ログ（harness-log.jsonl）

hook が dispatch / commit / session_start を自動記録する実行ログの存在と内訳を確認する
（`evolve-rules` の証拠源として使われる。仕様は `evolve-rules/SKILL.md` 手順1参照）:

```bash
f=.claude/harness-log.jsonl
if [ -s "$f" ]; then
  wc -l < "$f"
  grep -o '"event":"[^"]*"' "$f" | sort | uniq -c
  grep -o '"agent":"[^"]*"' "$f" | sort | uniq -c
else
  echo "harness-log.jsonl が無い、または空です"
fi
```

- ファイルが無い/空 → ⚠️（`.gitignore` 済みで git 管理外のため無くても異常とは限らない。
  hook が動いていない可能性と、新規プロジェクトでまだ記録が無い可能性の両方を示す。
  削除や再生成は行わず、確認を促すに留める）
- 存在する → ✅。総行数とイベント別・エージェント別の内訳を所見に添える

## 出力形式

```
## ハーネス診断結果

| 項目 | 状態 | 所見 |
|------|------|------|
| Engram | ✅/⚠️/❌ | <証拠と所見> |
| CodeGraph | ... | ... |
| settings JSON | ... | ... |
| ダングリング参照 | ... | ... |
| デッドルール | ... | ... |
| メモリ二重系統 | ... | ... |
| 実行ログ | ... | ... |

### 推奨アクション（優先度順）
1. <修正案>
```

❌ があれば最優先で対処を促す。全項目 ✅ なら「健全」と報告する。
