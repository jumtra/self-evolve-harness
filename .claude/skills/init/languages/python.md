# Python 生成モジュール

検出条件: `pyproject.toml` / `setup.py` / `requirements.txt` の存在。

## formatter

拡張子分岐（PostToolUse に合成）。ruff / black を検出順に:

```sh
*.py) ruff format --quiet "$file" 2>/dev/null && ruff check --fix --quiet "$file" 2>/dev/null;;  # ruff 優先
*.py) black --quiet "$file" 2>/dev/null;;  # ruff 未検出時
```

モノレポ時は他言語の formatter case と OR 束ねする。

## linter

- ruff: `ruff check`
- flake8: `flake8`（ruff 未検出時のフォールバック）

## typechecker

- mypy: `pyproject.toml [tool.mypy]` または `mypy.ini`
- pyright: `pyproject.toml [tool.pyright]` または `pyrightconfig.json`

## coding-rules

- すべての関数シグネチャに型ヒント・型アノテーションを付ける。戻り値の型も省略しない
- 曖昧な型（`Any` 等）の使用は最小限に
- 標準ライブラリ → サードパーティ → ローカルの順でimport。相対import禁止・絶対パスで書く
- 文字列補間は f-string を優先
- パス操作は `pathlib` を使い、文字列結合禁止
- 非公開は `_` プレフィクスで明示

## testing-rules

pytest 検出時:

- `tests/` 配下に `src/` と同じディレクトリ構造をミラー
- ファイル名: `test_<module>` プレフィクス
- テスト関数: `test_<関数名>_<状況>_<期待結果>`
- パラメトライズは `@pytest.mark.parametrize`

## architecture-guard

クリーンアーキテクチャ検出時（`domain/` + `usecases/` + `infrastructure/`）。PostToolUse に合成:

```sh
src/*/domain/*.py) grep -n 'from src\.[a-z_]*\.infrastructure' "$file" 2>/dev/null && echo 'ARCHITECTURE VIOLATION: domain/ から infrastructure/ をインポートしています。' || exit 0;;
src/*/usecases/*.py) grep -n 'from src\.[a-z_]*\.infrastructure' "$file" 2>/dev/null && echo 'ARCHITECTURE VIOLATION: usecases/ から infrastructure/ をインポートしています。' || exit 0;;
```

`src/` パスは検出したディレクトリ構造に応じて `/init` が調整する。
