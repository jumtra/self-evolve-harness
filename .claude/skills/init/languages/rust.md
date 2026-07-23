# Rust 生成モジュール

検出条件: `Cargo.toml` の存在。

## formatter

```sh
*.rs) rustfmt --edition 2021 "$file" 2>/dev/null;;
```

## linter

- clippy: `cargo clippy`

## typechecker

- rustc: コンパイル時に型検査（`cargo check`）

## coding-rules

- 型推論が自明な場合を除き、明示的な型注釈を避ける（Rust の慣習）
- `Result` / `Option` を早期リターン（`?` 演算子）で処理。`unwrap()` / `expect()` は本番コードで避ける
- `&str` と `String` の使い分けを意識。引数は `&str` を優先
- `clone()` は必要性を確認してから使う
- 所有権・ライフタイムを明示的に意識する

## testing-rules

- テストは対象モジュールと同ファイルの `#[cfg(test)] mod tests` に配置、または `tests/` 統合テスト
- 関数: `#[test] fn <関数名>_<状況>_<期待結果>()`
- パラメトライズ: 外部クレート `rstest` または手動ループ

## architecture-guard

ワークスペース検出時、各クレートの `src/lib.rs` と `src/main.rs` の依存方向を守衛。`domain` 相当クレートが `infrastructure` 相当クレートに依存しないよう `grep` 守衛。
