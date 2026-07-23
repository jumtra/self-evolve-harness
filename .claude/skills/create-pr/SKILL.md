---
name: create-pr
description: プロジェクトのPRテンプレートに従いGitHub Pull Requestを作成する
---

# Pull Request 作成

プロジェクトの `.github/pull_request_template.md` に従い、PR を作成します。

**引数（任意）:** "$ARGUMENTS"

## コンテキスト収集

- 現在のブランチ: !`git branch --show-current`
- main からの差分コミット: !`git log main..HEAD --oneline`
- 変更ファイル一覧: !`git diff main...HEAD --name-only`
- 変更サマリー: !`git diff main...HEAD --stat`

## 手順

1. **既存PRの確認**
   - `gh pr view` を実行し、すでにPRが存在する場合はURLを表示して終了する

2. **変更内容の分析**
   - 上記コンテキストを元に、変更の目的・内容・影響範囲を把握する

3. **PRタイトルの決定**
   - 引数 `$ARGUMENTS` が指定されていればそれを使用する
   - 指定がなければコミット履歴から推測する
   - 形式: `<type>: <概要>` （例: `feat: 評価指標にBLEUスコアを追加`）
   - type は `feat` / `fix` / `refactor` / `docs` / `test` / `chore` のいずれか

4. **PRボディの作成**
   以下のテンプレートを厳守し、各セクションを埋める：

   ```markdown
   ## 概要

   （変更内容と目的を1〜3文で記述）

   ## 変更内容

   - （変更点1）
   - （変更点2）

   ## 備考（任意）

   （レビュアーへの補足、デプロイ時の注意点などがあれば記述。なければ省略）

   ## 関連Issue（任意）

   （関連Issueがあれば記述。なければ省略）
   ```

   - 「概要」と「変更内容」は必須。内容のない任意セクションは省略してよい
   - HTMLコメント（`<!-- -->`）は除去する
   - 日本語で記述する

5. **リモートへプッシュ**
   - `git push origin HEAD` でブランチをプッシュする
   - すでにプッシュ済みの場合はスキップする

6. **PR作成**
   - `gh pr create --title "<タイトル>" --body "$(cat <<'EOF' ... EOF)"` で作成する
   - ベースブランチは `main`
   - 作成後にPR URLを表示する

7. **セッション保存**
   - PR作成後、`/save-session` を実行してセッションコンテキストを永続化する
