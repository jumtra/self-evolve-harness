# Terraform 生成モジュール

検出条件: `terraform/` ディレクトリ または `*.tf` ファイルの存在。

## formatter

```sh
*.tf) terraform fmt - "$file" 2>/dev/null;;
*.tfvars) terraform fmt - "$file" 2>/dev/null;;
```

## linter

- tflint: `tflint`（検出時）

## typechecker

- terraform validate: `terraform validate`（`terraform init` 後）

## coding-rules

- リソース名は `snake_case`。リソース種別はキャメルケース（Terraform 慣習）
- `variable` と `output` に `description` を必ず付ける
- `terraform { required_version }` を明示
- module は `modules/` 配下に、環境別構成は `envs-*/` 配下に配置
- バックエンド状態は `backend` ブロックで明示（remote state）

## testing-rules

- terraform test（`*.tftest.hcl`）を配置
- 構成の検証: `terraform validate` と `terraform plan` で事前確認

## architecture-guard

`modules/` と `envs-*/` の分離を守衛。`envs-*/` から `vendored-modules/` への参照方向を検査（`grep` で `source =` のパス確認）。

## recommended-tooling

検出ゼロ時の推奨（手順3b で提案に使う。formatter は `terraform fmt` 標準のため通常 linter のみ）:

| 用途 | 推奨 | 導入 | 最小設定 |
|---|---|---|---|
| linter | tflint | `brew install tflint` | `.tflint.hcl`（`plugin "terraform"` の enabled プリセット） |

> brew でのシステム変更になるため、導入前に必ずユーザー承認を取る。
