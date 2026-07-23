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
