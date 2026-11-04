#!/bin/sh
# seh が存在する間は seh hook に委譲する（fail-closed は seh 側）。
# seh 不在時のみ fail-open で通過させる（D11）。
if command -v seh >/dev/null 2>&1; then
  # exec だと seh のクラッシュ(exit 1)がそのまま返り、Claude では非ブロック扱いになる
  seh hook "$@"
  rc=$?
  if [ "${1:-}" = "PreToolUse" ] && [ "$rc" -ne 0 ] && [ "$rc" -ne 2 ]; then
    echo "seh hook が異常終了しました (exit $rc)。安全のためブロックします" >&2
    exit 2
  fi
  exit "$rc"
fi
# 毎回のノイズを避けるため、案内は SessionStart のときだけ出す
if [ "${1:-}" = "SessionStart" ]; then
  echo "警告: seh が未導入のため Hook を通過させます。導入: uv tool install git+https://github.com/jumtra/self-evolve-harness" >&2
fi
exit 0
