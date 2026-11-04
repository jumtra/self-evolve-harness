# v1 常時 Context ベースライン（NFR-011 / NFR-005）

- 基準: コミット `4c5ac19`（v1 最終コミット。P0 で `v1-baseline` タグを打つ）の blob
- 測定日: 2026-11-04
- 注意: 前回版は 988a019 基準だった。4c5ac19 で `memory.md` の増加などがあったため作り直した。作業ツリーの `CLAUDE.md` は未コミット変更を持ちうるので、**すべて `git show 4c5ac19:<path>` の内容**で測定した。
- 単位: 文字数 = Unicode コードポイント数（Python `len(str)`）、バイト数 = UTF-8、行数 = 改行文字数（`\n`）。

## 1. 常時ロードされる Context

「常時」= セッション開始時に無条件でモデル Context に入るもの。

| 対象 | 文字数 | バイト数 | 行数 |
| --- | ---: | ---: | ---: |
| `CLAUDE.md` | 4166 | 8156 | 114 |
| `AGENTS.md` | 1214 | 2420 | 45 |
| `.claude/rules/domain.md`（paths なし） | 871 | 1779 | 45 |
| `.claude/rules/memory.md`（paths なし） | 5290 | 10478 | 183 |
| `.claude/rules/workflow.md`（paths なし） | 1588 | 3216 | 68 |
| Skill description 6 件の合計（`disable-model-invocation` なし） | 674 | 1602 | 15 |
| Agent description 9 件の合計 | 1032 | 2484 | 33 |
| **合計** | **14835** | **30135** | **503** |

- Skill / Agent の description は frontmatter の `description:` ブロックを測る。文字数・バイト数は複数行を空白 1 個で連結した値、行数は `description:` 行を含む元の行数。
- **`disable-model-invocation: true` の Skill は description が常時 Context に載らない**（ユーザーが `/name` で明示起動したときだけロードされる）ため、常時合計から除いた。該当は 4 件で §1.3 に別掲する。
- `CLAUDE.md` と `AGENTS.md` を両方読むホストでは両方が常時対象になる。ホストごとの実ロード差は未測定。
- 合計は上表の各値の単純和。
- SessionStart Hook（settings.json #4）が `.agent-memory/MEMORY.md` の先頭 200 行を注入する。これは動的な Context で、4c5ac19 の blob は 100 文字 / 148 バイト / 3 行（見出しと注記のみ）。記憶が増えると膨らむ（Hook #5 の閾値は 20000B）ため合計には含めず、記録だけ残す。

### 1.1 常時載る Skill description 内訳

| ファイル | 文字数 | バイト数 | 行数 |
| --- | ---: | ---: | ---: |
| `skills/address-review` | 88 | 208 | 1 |
| `skills/brainstorm` | 187 | 427 | 5 |
| `skills/create-pr` | 42 | 84 | 1 |
| `skills/evolve-rules` | 102 | 256 | 3 |
| `skills/save-session` | 145 | 357 | 4 |
| `skills/self-review` | 110 | 270 | 1 |

### 1.2 Agent description 内訳

| ファイル | 文字数 | バイト数 | 行数 |
| --- | ---: | ---: | ---: |
| `agents/ci-triage` | 138 | 312 | 4 |
| `agents/design-reviewer` | 138 | 254 | 4 |
| `agents/evolver` | 148 | 366 | 4 |
| `agents/fixer` | 78 | 230 | 3 |
| `agents/implementer` | 145 | 379 | 4 |
| `agents/refactorer` | 55 | 145 | 3 |
| `agents/researcher` | 127 | 329 | 4 |
| `agents/reviewer` | 149 | 309 | 4 |
| `agents/test-writer` | 54 | 160 | 3 |

### 1.3 常時載らない Skill description（`disable-model-invocation: true`、参考）

| ファイル | 文字数 | バイト数 | 行数 |
| --- | ---: | ---: | ---: |
| `skills/create-skill` | 69 | 205 | 3 |
| `skills/desloppify` | 240 | 240 | 5 |
| `skills/harness-init` | 145 | 317 | 4 |
| `skills/harness-sync` | 151 | 293 | 4 |
| **小計（常時合計に含めない）** | **605** | **1055** | **16** |

## 2. 条件ロード（frontmatter に `paths:` を持つ rules）

対象ファイルを扱うときだけロードされる。常時合計には含めない。

| ファイル | 文字数 | バイト数 | 行数 |
| --- | ---: | ---: | ---: |
| `rules/architecture` | 785 | 1423 | 43 |
| `rules/coding` | 2526 | 5318 | 115 |
| `rules/debugging` | 1142 | 2062 | 54 |
| `rules/testing` | 3968 | 7316 | 125 |
| **小計** | **8421** | **16119** | **337** |

## 3. 測定コマンド（再現手順）

リポジトリルートで実行する。対象は 4c5ac19 の blob のみ（作業ツリーに依存しない）。

```bash
python3 - <<'PY'
import re, subprocess
R = "4c5ac19"
git = lambda *a: subprocess.run(["git", *a], capture_output=True, check=True).stdout.decode()
blob = lambda f: git("show", f"{R}:{f}")
fm = lambda t: re.match(r"---\n(.*?)\n---\n", t, re.S).group(1)
files = git("ls-tree", "-r", "--name-only", R, "--", ".claude").split("\n")

def row(label, t):
    print(label, len(t), len(t.encode()), t.count("\n"))

for f in ("CLAUDE.md", "AGENTS.md"):
    row(f, blob(f))
for f in filter(None, files):
    if "/rules/" in f:
        t = blob(f)
        print("PATHS" if re.search(r"^paths:", fm(t), re.M) else "ALWAYS", end=" ")
        row(f, t)
    if f.endswith("/SKILL.md") or "/agents/" in f:
        m = fm(blob(f))
        f_ = m + "\n"
        first = re.search(r"^description:([^\n]*)", f_, re.M).group(1)
        rest = re.search(r"^description:[^\n]*\n(.*?)(?=^\S|\Z)", f_, re.S | re.M).group(1)
        raw = (first + "\n" + rest).rstrip("\n")
        folded = " ".join(l.strip() for l in re.sub(r"^\s*[>|]\s*", "", raw).splitlines() if l.strip())
        hidden = bool(re.search(r"^disable-model-invocation:\s*true", m, re.M))
        print("HIDDEN" if hidden else "VISIBLE", f, len(folded), len(folded.encode()), raw.count("\n") + 1)
PY
```

`HIDDEN`（`disable-model-invocation: true`）の Skill は常時合計から除く。Agent は frontmatter に同フラグがないため全件 `VISIBLE`。単純な全体サイズだけなら `git show 4c5ac19:CLAUDE.md | wc -mcl` でも確認できる（`wc -m` はロケール依存）。

## 4. CLI 速度（NFR-005）

v1 には CLI が存在しないため、**ベースライン値はない**。基準値は P1 後（`seh` が動作する時点）に計測して本節へ追記する。

測定手順（P1 完了後に実施）:

1. クリーンな clone で `uv sync` 済みの状態にする。
2. `time uv run seh doctor` を 5 回連続実行し、1 回目（コールド）と 2〜5 回目（ウォーム）を分けて記録する。
3. 同様に `time uv run seh --help` を記録する。
4. 実行環境（OS、CPU、Python / uv のバージョン）を併記する。

| 計測対象 | コールド | ウォーム | 環境 |
| --- | --- | --- | --- |
| `uv run seh doctor` | 未測定 | 未測定 | 未測定 |
| `uv run seh --help` | 未測定 | 未測定 | 未測定 |
