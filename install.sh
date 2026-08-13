#!/bin/bash
# Install the Legwork skill into ~/.claude/skills/ as a live symlink install.
#
# SKILL.md references scripts via ${CLAUDE_SKILL_DIR}, which Claude Code
# substitutes to the skill's own directory for personal, project, and plugin
# installs alike. So this script symlinks the whole skill directory into
# ~/.claude/skills/ - every edit (scripts AND SKILL.md) is immediately live,
# with no per-file rewrite. Re-run only when you add a new skill directory.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILLS_ROOT="$HOME/.claude/skills"
HOOKS_ROOT="$HOME/.claude/hooks"
SETTINGS="$HOME/.claude/settings.json"
WITH_HOOK=0

for arg in "$@"; do
  case "$arg" in
    --with-hook) WITH_HOOK=1 ;;
    -h|--help)
      echo "usage: install.sh [--with-hook]"
      echo
      echo "  --with-hook  Also register the Stop hook that gates any legwork report"
      echo "               written in a session. Edits ~/.claude/settings.json"
      echo "               (backed up first). Off by default, because a global"
      echo "               settings change should be asked for, not assumed."
      exit 0 ;;
    *) echo "unknown option: $arg (try --help)"; exit 2 ;;
  esac
done

echo "=== Legwork skill installer (Claude Code) ==="
echo

# --- Dependencies ---
# The scripts are standard-library only, so python3 is the entire hard
# requirement. The floor is 3.9: every script carries
# `from __future__ import annotations`, so PEP 604 syntax parses there.
if ! command -v python3 >/dev/null 2>&1; then
  echo "Missing required dependency: python3"
  echo "  macOS:  brew install python3"
  echo "  Ubuntu: sudo apt install python3"
  exit 1
fi
if ! python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)'; then
  echo "Legwork needs Python 3.9 or newer; found $(python3 -V 2>&1)"
  exit 1
fi
echo "Dependencies OK ($(python3 -V 2>&1), standard library only)."
echo

# --- Install each skill in this repo as a full-directory symlink ---
mkdir -p "$SKILLS_ROOT"
for src in "$SCRIPT_DIR"/skills/*/; do
  src="${src%/}"
  name="$(basename "$src")"
  target="$SKILLS_ROOT/$name"
  echo "Installing '$name' -> $target"
  rm -rf "$target"            # replace any prior copy or partial-symlink install
  ln -sfn "$src" "$target"    # whole-directory symlink; ${CLAUDE_SKILL_DIR} resolves it
  chmod +x "$src"/scripts/*.py 2>/dev/null || true
done

echo
echo "Installed as directory symlinks - all edits (scripts and SKILL.md) are live. Re-run only when adding a new skill."
echo

# --- Optional Stop hook ---
# The gate is the one part of legwork that cannot be argued with, and it used to
# fire only when the agent remembered to run it. This wires it to the end of the
# turn instead. Opt-in: it edits a global settings file, which is not something
# an installer should do without being asked.
if [ "$WITH_HOOK" = "1" ]; then
  mkdir -p "$HOOKS_ROOT"
  ln -sfn "$SCRIPT_DIR/hooks/gate_on_stop.py" "$HOOKS_ROOT/legwork-gate.py"
  chmod +x "$SCRIPT_DIR/hooks/gate_on_stop.py"

  if [ -f "$SETTINGS" ]; then
    cp "$SETTINGS" "$SETTINGS.bak.$(date +%s)"
  fi

  python3 - "$SETTINGS" <<'PY'
import json, os, sys

path = sys.argv[1]
command = 'python3 ~/.claude/hooks/legwork-gate.py'

settings = {}
if os.path.exists(path):
    try:
        with open(path, encoding='utf-8') as handle:
            settings = json.load(handle)
    except ValueError:
        print('  settings.json is not valid JSON - leaving it alone.')
        sys.exit(1)

hooks = settings.setdefault('hooks', {})
stop = hooks.setdefault('Stop', [])

# Idempotent: re-running the installer must not stack duplicate hooks.
already = any(entry.get('command') == command
              for matcher in stop for entry in matcher.get('hooks', []))
if already:
    print('  Stop hook already registered.')
else:
    stop.append({'hooks': [{'type': 'command', 'command': command}]})
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as handle:
        json.dump(settings, handle, indent=2)
        handle.write('\n')
    print('  Registered the Stop hook in {}'.format(path))
PY
  echo "  A report that fails its gate will now block the end of the turn."
  echo "  Remove it by deleting the Stop entry from $SETTINGS."
else
  echo "Stop hook not installed. Re-run with --with-hook to have every legwork"
  echo "  report gated automatically at the end of a turn, instead of only when"
  echo "  the agent remembers to run check.py."
fi
echo

# --- Optional fallback provider ---
# Bright Data is a FALLBACK, not a requirement: retrieval runs on the host's
# built-in WebSearch/WebFetch. A missing CLI is a note, never a failure.
if command -v brightdata >/dev/null 2>&1 || command -v bdata >/dev/null 2>&1; then
  echo "Bright Data CLI found - fallback scraping available."
  echo "  Authenticate with 'brightdata login' if you have not already."
else
  echo "Note: Bright Data CLI not installed. Legwork works without it -"
  echo "  built-in WebSearch/WebFetch is the primary provider. You lose only"
  echo "  fallback scraping of blocked pages, Reddit threads and geo SERP."
  echo "  To enable later: npm install -g @brightdata/cli && brightdata login"
fi

echo
echo "Done. Try: 'legwork: compare managed Postgres options for a UK fintech'"
