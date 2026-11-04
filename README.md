# self-evolve-harness

`seh` は、複数の AI コーディングホスト向け設定を共通の正本から生成し、変更の検査と復旧を支援するツールです。Python 3.11 以上が必要です。Managed モードは公式 CLI を使う設計で、ベンダー SDK は不要です。

**状態:** v2.0.0a0 は開発中です。自己進化の CLI、ホスト互換性、Managed 実行と実機での動作は実装・検証が進行中です。導入前に計画を確認し、既存ファイルとバックアップを保全してください。

## 導入

このリポジトリのチェックアウトから `uv tool install -e .` で導入できます。対象リポジトリで次を実行します。

```sh
seh init --hosts all --plan
seh doctor --context
```

`--plan` の差分を確認後、利用者が対話端末で `seh init --hosts all --apply` を実行します。既存環境の移行は [移行手順](docs/migration-v1-to-v2.md) を参照してください。適用前には、対象リポジトリの変更を別途保存してください。

## 運用

- `seh sync --plan` は正本から生成される変更を表示します。確認後に `seh sync --apply` で適用します。
- `seh doctor` は設定と環境を診断します。`seh doctor --hosts all` による互換性診断は開発中です。
- `seh work` の Managed 実行は開発中です。[実行モード](docs/modes.md) の保証範囲と残課題を確認してください。
- `seh evolve` は候補の評価、昇格、巻き戻しに対応しています。候補の内容は現時点では手動で指定する必要があり、自動生成は開発中です。

Native の Hook だけではホスト外の変更を必ず阻止できません。必須 CI と branch protection が設定されていない環境は `NOT_ENFORCED` として扱ってください。Antigravity の Managed CLI は既定で `POLICY_BLOCKED` です。ホストや Provider の状態は [互換性](docs/provider-compatibility.md) を参照してください。

移行の復旧には表示された snapshot ID を使って `seh migrate rollback <snapshot-id>` を実行します。障害時の確認は [運用手順](docs/runbook.md)、設計上の境界は [アーキテクチャ](docs/architecture.md) を参照してください。
