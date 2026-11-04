# v1 常時 Context ベースライン（NFR-011 / NFR-005）

- 基準: コミット `988a019`（v1 最終コミット。後で `v1-baseline` タグが付く）の blob
- 測定日: 2026-11-04
- 注意: 作業ツリーの `CLAUDE.md` は 988a019 から未コミットの変更があるため、**すべて `git show 988a019:<path>` の内容**で測定した。
- 単位: 文字数 = Unicode コードポイント数（Python `len(str)`）、バイト数 = UTF-8、行数 = 改行文字数（`\n`）。

## 1. 常時ロードされる Context

「常時」= セッション開始時に無条件でモデル Context に入るもの。

| 対象 | 文字数 | バイト数 | 行数 |
| --- | ---: | ---: | ---: |
| `CLAUDE.md` | 2469 | 4545 | 91 |
| `AGENTS.md` | 1323 | 2679 | 54 |
| `.claude/rules/domain.md`（paths なし） | 871 | 1779 | 45 |
| `.claude/rules/memory.md`（paths なし） | 2637 | 4973 | 99 |
| `.claude/rules/workflow.md`（paths なし） | 1656 | 3390 | 74 |
| Skill description 10 件の合計 | 1079 | 2279 | 28 |
| Agent description 9 件の合計 | 1012 | 2462 | 33 |
| **合計** | **11047** | **22107** | **424** |

- Skill / Agent の description は frontmatter の `description:` ブロックを測る。文字数・バイト数は複数行を空白 1 個で連結した値、行数は `description:` 行を含む元の行数。
- `CLAUDE.md` と `AGENTS.md` を両方読むホストでは両方が常時対象になる。ホストごとの実ロード差は未測定。
- 合計は上表の各値の単純和（行数合計 = 91 + 54 + 45 + 99 + 74 + 28 + 33）。

### 1.1 Skill description 内訳

| ファイル | 文字数 | バイト数 | 行数 |
| --- | ---: | ---: | ---: |
| `skills/address-review` | 88 | 208 | 1 |
| `skills/brainstorm` | 75 | 221 | 3 |
| `skills/create-pr` | 42 | 84 | 1 |
| `skills/create-skill` | 69 | 205 | 3 |
| `skills/desloppify` | 240 | 240 | 5 |
| `skills/doctor` | 144 | 318 | 4 |
| `skills/evolve-rules` | 102 | 256 | 3 |
| `skills/harness-init` | 104 | 234 | 3 |
| `skills/save-session` | 105 | 243 | 4 |
| `skills/self-review` | 110 | 270 | 1 |

### 1.2 Agent description 内訳

| ファイル | 文字数 | バイト数 | 行数 |
| --- | ---: | ---: | ---: |
| `agents/ci-triage` | 138 | 312 | 4 |
| `agents/design-reviewer` | 138 | 254 | 4 |
| `agents/evolver` | 128 | 344 | 4 |
| `agents/fixer` | 78 | 230 | 3 |
| `agents/implementer` | 145 | 379 | 4 |
| `agents/refactorer` | 55 | 145 | 3 |
| `agents/researcher` | 127 | 329 | 4 |
| `agents/reviewer` | 149 | 309 | 4 |
| `agents/test-writer` | 54 | 160 | 3 |

## 2. 条件ロード（frontmatter に `paths:` を持つ rules）

対象ファイルを扱うときだけロードされる。常時合計には含めない。

| ファイル | 文字数 | バイト数 | 行数 |
| --- | ---: | ---: | ---: |
| `rules/architecture.md` | 785 | 1423 | 43 |
| `rules/coding.md` | 2534 | 5334 | 115 |
| `rules/debugging.md` | 1264 | 2344 | 63 |
| `rules/testing.md` | 3906 | 7150 | 127 |
| **小計** | **8489** | **16251** | **348** |

## 3. 測定コマンド（再現手順）

リポジトリルートで実行する（`src/seh/migration/v1_known_paths.json` が必要）。

```bash
python3 - <<'PY'
import json, re, subprocess
R = "988a019"
files = json.load(open("src/seh/migration/v1_known_paths.json"))["paths"]
blob = lambda f: subprocess.run(["git", "show", f"{R}:{f}"], capture_output=True, check=True).stdout.decode()
fm = lambda t: re.match(r"---\n(.*?)\n---\n", t, re.S).group(1)

def row(label, t):
    print(label, len(t), len(t.encode()), t.count("\n"))

for f in ("CLAUDE.md", "AGENTS.md"):
    row(f, blob(f))
for f, v in files.items():
    if v["kind"] == "rule":
        t = blob(f)
        print("PATHS" if re.search(r"^paths:", fm(t), re.M) else "ALWAYS", end=" ")
        row(f, t)
    if v["kind"] in ("skill", "agent"):
        f_ = fm(blob(f)) + "\n"
        first = re.search(r"^description:([^\n]*)", f_, re.M).group(1)
        rest = re.search(r"^description:[^\n]*\n(.*?)(?=^\S|\Z)", f_, re.S | re.M).group(1)
        raw = (first + "\n" + rest).rstrip("\n")
        folded = " ".join(l.strip() for l in re.sub(r"^\s*[>|]\s*", "", raw).splitlines() if l.strip())
        print(v["kind"], f, len(folded), len(folded.encode()), raw.count("\n") + 1)
PY
```

単純な全体サイズだけなら `git show 988a019:CLAUDE.md | wc -mcl` でも確認できる（`wc -m` はロケール依存）。

## 4. CLI 速度（NFR-005）

v1 には CLI が存在しないため、**ベースライン値はない**。基準値は P1 完了後（`seh` が動作する時点）に実測して本節へ追記する。

測定手順（P1 完了後に実施）:

1. クリーンな clone で `uv sync` 済みの状態にする。
2. `time uv run seh doctor` を 5 回連続実行し、1 回目（コールド）と 2〜5 回目（ウォーム）を分けて記録する。
3. 同様に `time uv run seh --help` を記録する。
4. 実行環境（OS、CPU、Python / uv のバージョン）を併記する。

| 計測対象 | コールド | ウォーム | 環境 |
| --- | --- | --- | --- |
| `uv run seh doctor` | 未測定 | 未測定 | 未測定 |
| `uv run seh --help` | 未測定 | 未測定 | 未測定 |
