#!/bin/bash
# Legwork setup: verify Python, and check the optional Bright Data fallback.
#
# There is deliberately no virtualenv here. Every script in this skill is
# Python standard library only, so a venv would install nothing and would only
# add a path that has to resolve identically under Claude, Codex and plugin
# installs. Removing it removes a whole class of "works on my install" bugs.
#
# Usage:
#   ./setup.sh              # verify Python; check the CLI is present + authenticated
#   ./setup.sh --reset      # re-run `brightdata login` to refresh credentials
#   ./setup.sh --no-prompt  # verify only; never prompt (for CI / unattended installs)
set -e

SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

RESET=0
NO_PROMPT=0
for arg in "$@"; do
    case "$arg" in
        --reset|--reconfigure) RESET=1 ;;
        --no-prompt)           NO_PROMPT=1 ;;
        --help|-h) sed -n '2,12p' "$0"; exit 0 ;;
        *) echo "Unknown arg: $arg" >&2; exit 1 ;;
    esac
done

# Auto-no-prompt when not attached to a terminal (e.g. CI).
if [ ! -t 0 ] && [ "$RESET" = 0 ]; then
    NO_PROMPT=1
fi

echo "=== Legwork Setup ==="

# --- Python ---
if ! command -v python3 &> /dev/null; then
    echo "Error: python3 not found" >&2
    exit 1
fi
if ! python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)'; then
    echo "Error: Legwork needs Python 3.9+; found $(python3 -V 2>&1)" >&2
    exit 1
fi
echo "Python: $(python3 -V 2>&1) (standard library only, no packages required)"

chmod +x "$SKILL_DIR/scripts/"*.py 2>/dev/null || true

# --- Bright Data CLI (optional fallback) ---
find_cli() { command -v brightdata 2>/dev/null || command -v bdata 2>/dev/null; }
CLI_BIN=$(find_cli || true)

# Bright Data is a FALLBACK provider (blocked pages, Reddit, geo SERP). The
# primary path is the host's built-in WebSearch/WebFetch, so a missing CLI is a
# note, not a failure - setup must still succeed without it.
if [ -z "$CLI_BIN" ]; then
    echo ""
    echo "Bright Data CLI: not installed (fallback scraping disabled)"
    echo "  Legwork works without it - built-in WebSearch/WebFetch is primary."
    echo "  To enable later:"
    echo "    npm install -g @brightdata/cli   # or: curl -fsSL https://cli.brightdata.com/install.sh | sh"
    echo "    $SKILL_DIR/setup.sh --reset"
    if [ "$RESET" = 1 ]; then
        echo "Error: --reset re-authenticates the Bright Data CLI, but it is not installed." >&2
        exit 1
    fi
    echo ""
    echo "=== Setup complete ==="
    exit 0
fi

echo "Bright Data CLI: $CLI_BIN ($("$CLI_BIN" --version 2>/dev/null || echo '?'))"

validate_cli() {
    echo ""
    echo "Testing the Bright Data CLI with a live search..."
    local out code
    out=$(python3 "$SKILL_DIR/scripts/bd_search.py" "brightdata setup test" -m general -c 1 2>&1 >/dev/null) && code=0 || code=$?
    if [ "$code" = 0 ]; then
        echo "Bright Data CLI OK."
        return 0
    fi
    echo "Validation failed (exit $code):" >&2
    echo "  $out" >&2
    case "$code" in
        2) echo "  -> authentication or quota error. Run \`$CLI_BIN login\` (or \`./setup.sh --reset\`)." >&2 ;;
        *) echo "  -> unexpected failure. Check your Bright Data dashboard and CLI install." >&2 ;;
    esac
    return "$code"
}

if [ "$NO_PROMPT" = 1 ]; then
    echo ""
    echo "Skipping the CLI auth check (--no-prompt). Authenticate with: $CLI_BIN login"
elif [ "$RESET" = 1 ]; then
    echo ""
    echo "--reset specified. Launching \`$CLI_BIN login\`..."
    "$CLI_BIN" login
    validate_cli || { echo "Login completed but validation still fails." >&2; exit 1; }
else
    if ! validate_cli; then
        echo ""
        read -r -p "Run \`$CLI_BIN login\` now? (Y/n): " do_login
        if [[ ! "$do_login" =~ ^[Nn]$ ]]; then
            "$CLI_BIN" login
            validate_cli || {
                echo "Login completed but validation still fails - fallback disabled." >&2
                echo "Legwork still works via the built-in providers." >&2
            }
        else
            echo "Skipping login. Fallback scraping stays disabled until: ./setup.sh --reset"
        fi
    fi
fi

echo ""
echo "=== Setup complete ==="
echo "Quick test:"
echo "  python3 $SKILL_DIR/scripts/bd_search.py \"ollama local llm\" -m general --json -c 5"
