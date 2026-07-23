# 汎用言語フォールバックモジュール

検出条件: 検出された言語に対応する `languages/*.md` 専用モジュールが存在しない場合
(例: Ruby, PHP, C#, Java, Kotlin, Elixir 等)。

このモジュールは固定内容ではなく**検出手順のプロトコル**。各セクションは `/init` 実行時に
このプロトコルに従って実プロジェクトから導出する。

## 言語特定(前段)

1. ソースファイル拡張子の分布を集計: `git ls-files | sed -n 's/.*\.//p' | sort | uniq -c | sort -rn`
2. 設定ファイルで確定: `Gemfile`(Ruby) / `composer.json`(PHP) / `*.csproj`(C#) /
   `pom.xml`・`build.gradle`(Java/Kotlin) / `mix.exs`(Elixir) 等

## formatter

その言語の標準フォーマッタ候補を挙げ、**存在確認できたものだけ**採用する:

1. 候補列挙(例: Ruby→rubocop, PHP→php-cs-fixer, C#→`dotnet format`,
   Java→google-java-format/spotless, Kotlin→ktlint, Elixir→`mix format`)
2. `command -v <tool>` + 設定ファイル存在(`.rubocop.yml` 等)の両方で確認する
3. 検出できたツールのみ formatter case(PostToolUse 拡張子分岐)に載せる:

```sh
*.<ext>) <formatter-cmd> "$file" 2>/dev/null;;
```

4. 検出ゼロならフォーマッタフックをスキップする。**推測でコマンドを書かない**

## linter

formatter と同じプロトコル(候補列挙 → `command -v` + 設定ファイルで確認 → 検出分のみ採用)。

## typechecker

formatter と同じプロトコル。検出できた場合は保護対象設定ファイルリストにも追加する
(`/init` 手順3と同じ扱い)。

## coding-rules

言語コミュニティの標準規約(命名・イディオム)を、実プロジェクトの既存コードと突合して生成する:

- 既存コードを数ファイル読み、命名・import スタイルの実態を確認する
- 実態と一致する規約のみ書く。実態と矛盾する一般論は書かない

## testing-rules

テストディレクトリ(`test/` `tests/` `spec/` 等)とテストファイル命名の実態を確認して生成する。
テスト基盤が未検出ならセクションごとスキップする。

## architecture-guard

`/init` 手順4のディレクトリ構造分析結果からパスパターンを導出する(言語非依存ロジック):

```sh
<domain-path-pattern>) grep -n '<infrastructure-import-pattern>' "$file" 2>/dev/null && echo 'ARCHITECTURE VIOLATION: domain 層から infrastructure 層を参照しています。' || exit 0;;
```

フラット構造はスキップ。import 文の grep パターンは言語特定の結果に応じて調整する。
