# 自己進化の反映先に hook を追加 設計

## 目的

`/evolve-rules`（evolver エージェント）が蓄積フィードバックを反映する先に、
これまでの rules / skills / agents に加えて **hook（`.claude/settings.json`）** を
追加する。決定論的に検出・防止できる繰り返し失敗を、モデルの注意力に頼るルールから
機械的強制へエスカレーションできるようにする。

## リスク認識（hook 固有）

- **即時発火**: settings.json は作業ツリーに入った時点でセッションに効く（コミット前でも）。
  壊れた hook は以降のツール呼び出しを止める。
- **JSON はコメント不可**: 未展開プレースホルダを残すとリテラル実行で破綻。
- **init との契約**: フォーマッタ/アーキ守衛/CI ゲートは `/harness-init` が生成する領域。

## 決定事項

- 適用方式: **検証付き自動適用**（JSON妥当性・プレースホルダ検査・dry-run・fail-open の
  4ゲート全通過で初めて適用。落ちたら見送り報告）
- 操作範囲: **追加 + 自作 hook の改修のみ**。init 生成の安全フックと evolve 由来でない
  既存 hook の削除・改変はしない。

## 変更ファイル

| ファイル | 変更 |
|---|---|
| `skills/evolve-rules/SKILL.md` | 反映先リストに hook 追加 / 2d に hook 判定基準（優先5・最後の手段）/ `#### hook を作成・改修する場合`（規約は hooks-boilerplate.md 参照・操作範囲・4ゲート）/ 手順3 適用リスト・見送り規定 / 手順5 ログに hook 識別情報 |
| `agents/evolver.md` | description・本文の反映先に hook 追加 / 制約に検証ゲート＋限定操作 / 完了報告に hook 検証証拠 |
| `_reference.md` | 「ハーネス自動進化」説明に hook を追加 |

## 判定基準（2d 追加分）

file_path / コマンド文字列で機械的に検出でき、指示的ルールを入れても繰り返し無視される
失敗 → hook。ルールからのエスカレーションとして使う。指示的アーティファクトで足りるなら
hook にしない（強制力・blast radius が大きいため最後の手段）。

## 必須検証ゲート

1. JSON 妥当性（`python3 -m json.tool`）
2. プレースホルダ検査（`<...>` トークン無し）
3. dry-run（サンプル stdin JSON で想定通り exit 0/2）
4. fail-open（パース失敗入力でも exit 0）

## スコープ外

- SessionStart の AUTO-EVOLVE 発火ロジック（件数トリガー）は不変
- `/harness-init` の hook 生成契約は不変（evolve は init 生成物を上書きしない）
