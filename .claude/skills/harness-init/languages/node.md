# Node.js / TypeScript 生成モジュール

検出条件: `package.json` の存在。

## formatter

```sh
*.{js,jsx,ts,tsx,json,css,md}) prettier --write "$file" 2>/dev/null;;  # prettier 検出時
*.{js,jsx,ts,tsx}) biome format --write "$file" 2>/dev/null;;  # biome 検出時
```

## linter

- eslint: `.eslintrc*` / `eslint.config.*`
- biome: `biome.json`（eslint 代替可）

## typechecker

- tsc: `package.json` の typescript 依存
- 検出時: `tsc --noEmit`

## coding-rules

- 型アノテーション: TypeScript では暗黙 `any` 禁止（`strict: true` 推奨）
- import 順序: 標準→サードパーティ→ローカル（eslint-plugin-import または biome の import 整序）
- 名前付き export をデフォルトとする。`export default` は避ける（一貫性のため）
- 文字列補間はテンプレートリテラルを優先
- パス操作は Node.js `path` モジュールを使う（文字列結合禁止）

## testing-rules

検出したフレームワークに応じて:

- vitest / jest: `test('...', () => {})` または `it('...', () => {})`。`*.test.ts` / `*.spec.ts`
- 配置: テスト対象と同階層（`src/foo.ts` ↔ `src/foo.test.ts`）または `__tests__/`
- パラメトライズ: `test.each`

## architecture-guard

フロント（React/Next）検出時は `components/` `pages/` `app/` の依存方向を守衛。レイヤード検出時は `handlers/` `services/` `models/` の import 方向。

```
# 例: Next.js で pages/ から components/ への import は許可、逆は禁止等
# /harness-init が構造分析から個別生成
```
