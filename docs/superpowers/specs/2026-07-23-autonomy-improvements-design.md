# ハーネス自律性向上 設計（Tier0 + P1/P2/P3 + メモリ統合）

## 目的

「人間のFBを環境に焼き込み、Claude が必要な agent/skill/hook を自律的に足す」思想を
強化する。評価で見つかった自己改善ループの穴を塞ぐ。

## 実装項目

### Tier 0: バグ修正
- `save-session/SKILL.md`: 別プロジェクト名 `cs-summarization-onprem` ハードコード →
  `basename $(git rev-parse --show-toplevel)` / `mem_current_project` 参照に汎用化
- `reviewer.md` / `design-reviewer.md`: 「クリーンアーキテクチャ」決め打ち →
  `architecture.md 参照`（フラット構造ならスキップ）に汎用化
- `memory.md`: 進化の反映先に hook を追記（先行変更との整合）

### P1: フィードバック捕捉フック（UserPromptSubmit）
- settings.json に UserPromptSubmit フック追加。修正語（違う/ちがう/そうじゃな/じゃなくて/
  こうして/直して/やめて/戻して/revert）検出でリマインダを stdout 注入。ブロックしない・
  常に exit 0（fail-open）。prompt 抽出はスペース有無の両変異にフォールバック
- hooks-boilerplate.md に記述（/init が全プロジェクトで再現）

### P2: 進化の効果測定（evolve-rules）
- 手順 2e「前回進化の効果検証」追加: changelog の前回エントリ root cause が適用日以降に
  再発したかを Engram 検索で確認。効果あり/なし/ロールバック候補を判定・記録
- changelog テンプレに `予測効果:` / `検証:` 行を追加（初回は「未検証」）

### P3: /doctor 自己診断 + SessionStart 健全性プローブ
- 新規 `skills/doctor/SKILL.md`: Engram到達性+観測件数 / CodeGraph / settings JSON妥当性 /
  ダングリング参照 / デッドルール / メモリ二重系統 を検査し修正案を提示（破壊的自動修正なし）
- settings.json SessionStart に軽量プローブ追加（engram不在・settings.local.json破損で1行警告、
  fail-open）。settings.json 自体の破損は /doctor で明示検査

### メモリ統合ハードニング（memory.md）
- Engram を唯一の記憶層と明記。組み込みファイル memory（memory/・MEMORY.md）は使わない・
  指示競合時はこのルール優先
- セッション開始時 `mem_context` で想起を義務化

## 検証（証拠）
- settings.json: `python3 -m json.tool` パス
- P1 hook dry-run: 修正語(spaced/compact)で発火・非修正で無音・壊れ入力で fail-open・全 exit 0
- 健全性プローブ dry-run: 正常環境で無音・exit 0
- /doctor ライブ実行: Engram 1.19.0 稼働 / CodeGraph 1.4.1 / settings 両JSON OK /
  ダングリング参照は doctor自身の例示のみ（スラッシュ除去で解消）/ 本プロジェクトにファイルmemoryなし

## 波及（/init 契約）
- hooks-boilerplate.md と init SKILL.md 手順6 に UserPromptSubmit・SessionStart 2種を
  「常に含める言語非依存フック」として追記。新規プロジェクトでも自動再現される
- _reference.md の自動動作表・スキル表・ファイル構成に反映

### Tier 3: 自律実行を広げる新エージェント（追加実装）
- `agents/ci-triage.md`: CI失敗を種別分類し委譲先を提案（Read/Bash のみ・修正しない）。
  fixer の3ストライク・禁止事項に準拠
- `agents/researcher.md`: 外部情報調査（Read/WebSearch/WebFetch）。出典必須・コードは書かない
- `_reference.md` のエージェント表・構成図に反映（欠落していた evolver.md も構成図に追記）

検証: 新規2エージェントの frontmatter（name/description/model/tools）妥当性 OK、
_reference の全8エージェントが実体と一致。

## 既知の非スコープ
- Engram 1.20.0 への更新は任意（ユーザー環境の brew 操作のため案内のみ）
