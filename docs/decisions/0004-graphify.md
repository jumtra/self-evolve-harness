# ADR-0004: Code Intelligence Provider（Graphify / CodeGraph）の CLI 契約

- 状態: 採用（2026-11-04）

## Graphify

- 正式な提供元は **`Graphify-Labs/graphify`**（PyPI パッケージ名 `graphifyy`。y が2つ。コマンド名は `graphify`）。根拠は、PyPI の Project links が同リポジトリを指していること。
- **`EaZtoday/graphifyy` は個人の fork なので許可しない**。それ以外の非公式 `graphify*` パッケージも同様に許可しない。
- 導入方法: `uv tool install graphifyy`（Python 3.10 以上）。**v2 は自動インストールしない**（D10）。導入は `seh` が dry-run で手順を示し、ユーザーが行う。
- CLI 契約（Adapter が使う範囲）:
  - 構築: `graphify .`（`--update`、`--no-viz`）。出力先は `graphify-out/graph.json`。
  - 問い合わせ: `graphify query <q>`、`graphify explain <symbol>`、`graphify path <a> <b>`。
  - 終了コード: 0 = 回答あり、3 = 名前が曖昧、**4 = 該当なし（Result `NOT_FOUND`）**。
  - LLM を使わないこと: `GRAPHIFY_BACKEND=none` を必ず設定し、コード解析だけを行う。
- Capability の対応:

  | Capability | 対応する CLI | 扱い |
  |---|---|---|
  | `index` | `graphify .` | OK |
  | `search_symbols` | `query` | OK |
  | `dependencies` | `explain` / `path` | OK |
  | `change_impact` | `graph.json` の走査 | ADAPTED |
  | `affected_tests` | 対応なし | **UNSUPPORTED** |

- このマシンには導入しない。テストは fake（記録済みの出力）で行う。
- ライセンスは資料によって表記が異なる（Apache-2.0 / MIT）。導入前に LICENSE ファイルの実物で確認することを、利用者向けの手順として README に書く。
- MCP の起動コマンドと `graph.json` の詳細スキーマは未確認のため、Adapter は `schema_version` が想定外のときに ERROR を返す。

## CodeGraph（`colbymchenry/codegraph`、ライセンスは MIT。手元の版は 1.4.1）

- 構築: `codegraph init [path]` で初回、`codegraph sync` で差分更新。DB は `.codegraph/codegraph.db`。
- Capability の対応:

  | Capability | 対応する CLI |
  |---|---|
  | `search_symbols` | `codegraph query <q>` |
  | `dependencies` | `codegraph callers` / `callees <symbol>` |
  | `change_impact` | `codegraph impact <symbol>` |
  | `affected_tests` | `codegraph affected [files...]` |

- `--json` に対応しているかは、各サブコマンドの `--help` で確認（probe）してから使う。対応していなければテキスト出力をパースする。
- README に載っている `implementations` と `cycles` は 1.4.1 の `--help` に無いため使わない。
- 実スモークは一時ディレクトリの fixture リポジトリで、HOME も一時ディレクトリにして実行する（D10）。

## 出典
- https://github.com/Graphify-Labs/graphify
- https://pypi.org/project/graphifyy/
- https://github.com/EaZtoday/graphifyy
- https://github.com/colbymchenry/codegraph
