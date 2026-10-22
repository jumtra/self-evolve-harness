# Java 生成モジュール

検出条件: `pom.xml`（Maven）または `build.gradle` / `build.gradle.kts`（Gradle）の存在。

## formatter

```sh
*.java) command -v google-java-format >/dev/null 2>&1 && google-java-format -i "$file" 2>/dev/null;;
```

- spotless 導入時（`spotless` プラグイン検出）は `./gradlew spotlessApply` / `mvn spotless:apply` を優先

## linter

- checkstyle: `mvn checkstyle:check` / `./gradlew checkstyleMain`（設定検出時）
- spotbugs: `mvn spotbugs:check` / `./gradlew spotbugsMain`（設定検出時）
- PMD: `mvn pmd:check`（設定検出時）

## typechecker

- javac: ビルド（`mvn compile` / `./gradlew build`）が型検査を内包する

## coding-rules

- クラスは `PascalCase`、メソッド・フィールドは `camelCase`、定数は `UPPER_SNAKE_CASE`
- `null` 返却より `Optional<T>`。可能な限り不変（`final` フィールド・イミュータブルオブジェクト）
- 例外は検査例外/非検査例外を意図的に使い分ける。握りつぶし（空 catch）禁止
- 依存注入はコンストラクタ経由。フィールドインジェクションを避ける
- ストリーム API は可読性を損なわない範囲で使う（過度なネストを避ける）

## testing-rules

- テストは `src/test/java/` にミラー配置。命名 `<対象>Test`
- フレームワークは JUnit 5（`@Test` / `@ParameterizedTest`）。アサーションは AssertJ / JUnit assertions
- パラメトライズは `@ParameterizedTest` + `@MethodSource` / `@CsvSource`（各ケースに意味のある名前）
- モックは Mockito（`@Mock` / `mock()`）。外部依存は境界インターフェースで差し替える

## architecture-guard

レイヤード/ヘキサゴナル構成（`domain/` `application/` `infrastructure/` 等のパッケージ）検出時、
`domain` パッケージが `infrastructure` を import しないよう `grep` 守衛（他言語モジュールと同方針）。

## recommended-tooling

検出ゼロ時の推奨（手順3b で提案に使う。Java はビルドツール統合が標準）:

| 用途 | 推奨 | 導入 | 最小設定 |
|---|---|---|---|
| formatter | Spotless + google-java-format | ビルドファイルに Spotless プラグイン追加（Gradle: `plugins` 節 / Maven: `pom.xml`）を提案して適用 | プラグインの最小設定ブロック |
| linter（任意） | Spotless と同時に checkstyle をビルドへ統合 | 同上（ビルドツール依存。個別 install ではない） | プラグインの最小設定ブロック |

> ビルドファイルへの変更はユーザー承認後に行う。設定保護フックの対象になっていれば承認扱いを明示する。
