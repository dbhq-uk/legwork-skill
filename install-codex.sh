#!/bin/bash
# Install the Legwork skill into ~/.codex/skills/ for Codex.
#
# Codex does not substitute ${CLAUDE_SKILL_DIR}, so this script rewrites that
# variable to each skill's installed Codex path and symlinks the supporting
# directories (edits stay live). Re-run after editing a SKILL.md.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILLS_ROOT="$HOME/.codex/skills"

echo "=== Legwork skill installer (Codex) ==="
echo

if ! command -v python3 >/dev/null 2>&1; then
  echo "Missing required dependency: python3"
  exit 1
fi
if ! python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)'; then
  echo "Legwork needs Python 3.9 or newer; found $(python3 -V 2>&1)"
  exit 1
fi
echo "Dependencies OK ($(python3 -V 2>&1), standard library only)."
echo

for src in "$SCRIPT_DIR"/skills/*/; do
  src="${src%/}"
  name="$(basename "$src")"
  target="$SKILLS_ROOT/$name"
  echo "Installing '$name' -> $target"
  mkdir -p "$target"
  # Every directory SKILL.md can reference, not just scripts: the reference
  # docs, templates and schemas are all addressed via ${CLAUDE_SKILL_DIR},
  # so each one has to exist under the rewritten path too.
  for sub in scripts reference references templates schemas tests; do
    [ -d "$src/$sub" ] && ln -sfn "$src/$sub" "$target/$sub"
  done
  chmod +x "$src"/scripts/*.py 2>/dev/null || true
  sed "s#\${CLAUDE_SKILL_DIR}#$target#g" \
    "$src/SKILL.md" > "$target/SKILL.md"
done

echo
echo "Installed for Codex. Bright Data is optional; run 'brightdata login' only if you want fallback scraping."
