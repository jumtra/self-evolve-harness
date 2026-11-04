# ホストと Provider の互換性

| 対象 | 状態と制約 |
| --- | --- |
| Claude / Codex / OpenCode | 設定描画と CLI Runner を実装中。ホストの版、認証、実効権限によって利用可能な機能が異なります。実環境で確認してください。 |
| Google Antigravity | 設定描画は可能。第三者による Managed CLI 利用は既定で `POLICY_BLOCKED`。利用条件と許可の確認なしに自動起動しません。 |
| CodeGraph | 既存 CLI を利用するアダプタ。版 1.4.1 で一時リポジトリのスモーク確認済み。 |
| Graphify | fake によるテストのみ。`query`、`explain`、出力形式は実機未検証です。導入前に提供元とライセンスを確認してください。自動インストールはしません。 |
| ファイルメモリ / Engram | 選択式。Engram は別途インストールが必要です。 |

CLI が存在しても認証、権限、利用条件や個々の機能まで保証されません。未検証の機能は `UNVERIFIED` として扱ってください。各ホスト向けの互換性レポートは開発中です。詳細な CLI 契約と調査の根拠は [Provider の決定記録](decisions/0004-graphify.md) を参照してください。
