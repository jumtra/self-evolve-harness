# C# 生成モジュール

検出条件: `*.csproj` / `*.sln` の存在。

## formatter

```sh
*.cs) command -v dotnet >/dev/null 2>&1 && dotnet format --include "$file" 2>/dev/null;;
```

## linter

- Roslyn アナライザー: csproj の `<EnableNETAnalyzers>true</EnableNETAnalyzers>` または
  `.editorconfig` の `dotnet_diagnostic` 設定を検出。検出時は `dotnet build` で警告を拾う
- StyleCop.Analyzers: csproj のパッケージ参照で検出

## typechecker

- C# コンパイラ（`dotnet build`）が型検査を担う

## coding-rules

- nullable 参照型を有効化し、`!`（null 許容演算子）の乱用は避ける
- 非同期メソッド名は `Async` サフィックスを付ける
- 型・public メンバは PascalCase、private フィールドは `_camelCase`
- 文字列補間は `$"..."` を優先

## testing-rules

xUnit / NUnit / MSTest 検出時:

- テストプロジェクトは `<対象>.Tests/`。ファイル名 `<対象>Tests.cs`
- メソッド名: `<対象>_<状況>_<期待結果>`（例: `Parse_MissingKey_Throws`）
- `[Theory]` + `[InlineData]` で入力バリエーションを表す

## architecture-guard

レイヤード検出時（`Controllers/`・`Services/`・`Repositories/` 等）、
`Controllers` 層から `Repositories` 層への直接依存等の方向違反を `grep` 守衛。
パターンは `/harness-init` が構造分析から個別生成する。

## recommended-tooling

検出ゼロ時の推奨（手順3b で提案に使う。formatter は SDK 内蔵の `dotnet format` が多い）:

| 用途 | 推奨 | 導入 | 最小設定 |
|---|---|---|---|
| linter | Roslyn アナライザー（SDK 同梱） | 導入不要。csproj に `<EnableNETAnalyzers>true</EnableNETAnalyzers>` を追加する提案 | 同上（csproj 編集は承認後） |
| 整形規律（任意） | `.editorconfig` | 生成のみ | `dotnet_diagnostic` + 整形設定の最小ブロック |

> csproj / .editorconfig の編集はユーザー承認後に行う。
