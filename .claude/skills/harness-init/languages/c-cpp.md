# C / C++ 生成モジュール

検出条件: `CMakeLists.txt` / `compile_commands.json` / `*.c` `*.h` `*.cpp` `*.hpp` の存在。

## formatter

```sh
*.{c,h,cpp,hpp,cc,cxx}) command -v clang-format >/dev/null 2>&1 && clang-format -i "$file" 2>/dev/null;;
```

## linter

- clang-tidy: `clang-tidy`（`compile_commands.json` がある場合は `-p .`）
- cppcheck: `cppcheck --enable=warning`（検出時のフォールバック）

## typechecker

- コンパイラの警告レベルで代用する（`-Wall -Wextra`）。別途型検査ツールは標準ではない

## coding-rules

- C: 名前空間がないため関数・マクロにモジュール prefix（例: `db_`）を付ける
- C++: RAII とスマートポインタを使い、所有権を持つ生ポインタを避ける
- C++: 値は `const` をデフォルトにする。参照渡しは `const &`
- ヘッダは include guard（または `#pragma once`）を必ず付ける
- C++: `nullptr` を使い、NULL/0 は使わない

## testing-rules

googletest / Catch2 / doctest 検出時:

- `tests/` 配下に配置。`TEST(<Suite>, <状況>_<期待結果>)` の命名
- 1 アサーション = 1 EXPECT_*。 parameterized test は googletest の `TEST_P`

## architecture-guard

`include/`（公開ヘッダ）と `src/`（実装）の分離検出時、`src/` の実装ファイルが内部ヘッダ以外の `include/` を不用意に参照しない等、構成に応じて `/harness-init` が個別生成する。

## recommended-tooling

検出ゼロ時の推奨（手順3b で提案に使う）:

| 用途 | 推奨 | 導入 | 最小設定 |
|---|---|---|---|
| formatter | clang-format | `brew install llvm`（PATH 追加の案内あり） | `.clang-format`（`BasedOnStyle: Google` 1行） |
| linter | clang-tidy | 同上（llvm に同梱） | `.clang-tidy`（`Checks: 'clang-analyzer-*'` 等の最小1行。`compile_commands.json` が無い場合は CMake の `-DCMAKE_EXPORT_COMPILE_COMMANDS=ON` を案内） |

> brew でのシステム変更になるため、導入前に必ずユーザー承認を取る。
