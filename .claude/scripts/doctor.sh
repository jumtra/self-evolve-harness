#!/usr/bin/env bash
# Harness health check. Deterministic, so it lives here instead of a skill (no per-turn description cost).
# Usage: bash .claude/scripts/doctor.sh   (read-only; prints OK/WARN/NG with evidence)
set -u
cd "${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel 2>/dev/null || pwd)}" || exit 1
ng=0
ok() { printf 'OK    %s\n' "$*"; }
warn() { printf 'WARN  %s\n' "$*"; }
bad() { printf 'NG    %s\n' "$*"; ng=1; }

# 1. file memory index size (loaded every session; limit 25KB / 200 lines)
root=$(dirname "$(git rev-parse --path-format=absolute --git-common-dir 2>/dev/null)")
mem="$HOME/.claude/projects/$(printf %s "$root" | tr '/.' '--')/memory"
if [ -f "$mem/MEMORY.md" ]; then
  bytes=$(wc -c <"$mem/MEMORY.md")
  [ "$bytes" -gt 20000 ] && warn "MEMORY.md ${bytes}B (limit 25KB; shorten index lines to 150 chars)" || ok "MEMORY.md ${bytes}B"
else
  warn "no MEMORY.md at $mem"
fi

# 2. codegraph
if command -v codegraph >/dev/null 2>&1; then ok "codegraph $(codegraph --version 2>&1 | head -1)"; else warn "codegraph not found"; fi
[ -d .codegraph ] || warn ".codegraph missing (run codegraph init)"

# 3. settings JSON validity (a broken settings.json silently disables hooks)
for f in .claude/settings.json .claude/settings.local.json; do
  [ -f "$f" ] || continue
  python3 -m json.tool "$f" >/dev/null 2>&1 && ok "valid $f" || bad "invalid JSON: $f"
done

# 4. dangling /skill references (built-ins and placeholders excluded)
builtin='loop|schedule|init|config|clear|compact|context|cost|model|mcp|memory|rewind|resume|effort|help|status|hooks|agents|usage|stats|skill-name|name|skills'
dangling=$(grep -rhoE '`/[a-z][a-z0-9-]+(`| [^`]*`)' .claude/rules .claude/skills .claude/agents CLAUDE.md AGENTS.md 2>/dev/null |
  sed -E 's/^`\/([a-z0-9-]+).*/\1/' | sort -u | grep -vxE "$builtin" |
  while read -r n; do [ -d ".claude/skills/$n" ] || [ -f ".claude/agents/$n.md" ] || echo "$n"; done)
[ -z "$dangling" ] && ok "no dangling skill references" || warn "referenced but missing: $(echo "$dangling" | tr '\n' ' ')"

# 5. always-loaded context size (rules without paths:, CLAUDE.md, AGENTS.md)
total=0
for f in CLAUDE.md AGENTS.md; do [ -f "$f" ] && total=$((total + $(wc -c <"$f"))); done
for f in .claude/rules/*.md; do [ -f "$f" ] || continue; sed -n 1,8p "$f" | grep -q '^paths:' || total=$((total + $(wc -c <"$f"))); done
[ "$total" -gt 40000 ] && warn "always-loaded files total ${total}B (move details to paths: rules or scripts)" || ok "always-loaded files ${total}B"

# 6. execution log
log=.claude/harness-log.jsonl
if [ -s "$log" ]; then ok "harness-log: $(wc -l <"$log") lines"; grep -o '"event":"[^"]*"' "$log" | sort | uniq -c | sed 's/^/        /'; else warn "harness-log.jsonl empty or missing (ignored by git; may be fresh)"; fi

# 7. skill audit: per-turn description cost and usage (from harness-log "skill" events)
echo "--- skills (listed = description is loaded every turn)"
for d in .claude/skills/*/; do
  n=$(basename "$d"); f="$d/SKILL.md"; [ -f "$f" ] || continue
  desc=$(awk '/^description:/{sub(/^description: *>? */,"");print;f=1;next} f&&/^  /{print;next} f{exit}' "$f" | wc -c)
  manual=$(sed -n 1,12p "$f" | grep -c '^disable-model-invocation: true')
  uses=0; [ -s "$log" ] && uses=$(grep -c "\"event\":\"skill\",\"name\":\"$n\"" "$log")
  state=listed; [ "$manual" -gt 0 ] && state=manual
  line=$(printf '%-18s desc=%4sB %-7s uses=%s' "$n" "$desc" "$state" "$uses")
  if [ "$uses" -eq 0 ] && [ "$state" = listed ] && [ -s "$log" ]; then warn "$line (unused: make manual-only, merge, or turn into a script)"; else ok "$line"; fi
done

exit $ng
