# Go 生成モジュール

検出条件: `go.mod` の存在。

## formatter

```sh
*.go) gofmt -w "$file" 2>/dev/null; goimports -w "$file" 2>/dev/null;;
```

## linter

- golangci-lint: `golangci-lint run`（検出時）
- go vet: `go vet`（標準）

## typechecker

- Go コンパイラ: `go build`（型検査内包）

## coding-rules

- エクスポート識別子は `PascalCase`、非エクスポートは `camelCase`
- エラーは戻り値で返す（`if err != nil`）。`panic` は回復不能時のみ
- インターフェースは利用者側で定義する（"accept interfaces, return structs"）
- ポインタ vs 値: 大きな構造体や変更が必要な場合のみポインタ
- `context.Context` は第一引数に渡す

## testing-rules

- テストは対象ファイルと同階層: `foo.go` ↔ `foo_test.go`
- 関数: `func Test<関数名>_<状況>_<期待結果>(t *testing.T)`
- サブテスト: `t.Run`
- パラメトライズ: テーブル駆動テスト（`tests := []struct{...}` + `t.Run`）

## architecture-guard

`cmd/` `internal/` `pkg/` 構成検出時、`internal/` 配下のパッケージ依存方向を守衛。ドメイン層パッケージがインフラ層パッケージを import しないよう `grep` 守衛。
