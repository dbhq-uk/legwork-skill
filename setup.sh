#!/bin/bash
# Set up deep-research skill: Python venv + Bright Data CLI auth check.
#
# Usage:
#   ./setup.sh              # Provision venv. Verify CLI is installed + authenticated.
#   ./setup.sh --reset      # Re-run `brightdata login` to refresh credentials.
#   ./setup.sh --no-prompt  # Provision venv only. Skip CLI auth check.
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$SCRIPT_DIR"
VENV_DIR="$SKILL_DIR/.venv"

RESET=0
NO_PROMPT=0
for arg in "$@"; do
    case "$arg" in
        --reset|--reconfigure) RESET=1 ;;
        --no-prompt)           NO_PROMPT=1 ;;
        --help|-h)
            sed -n '2,9p' "$0"
            exit 0
            ;;
        *) echo "Unknown arg: $arg" >&2; exit 1 ;;
    esac
done

# Auto-no-prompt when run from a non-interactive shell (e.g. install.sh --all in CI).
if [ ! -t 0 ] && [ "$RESET" = 0 ]; then
    NO_PROMPT=1
fi

echo "=== Deep Research Skill Setup ==="

# --- Python venv ---
if ! command -v python3 &> /dev/null; then
    echo "Error: python3 not found"
    exit 1
fi

PYTHON_VERSION=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
echo "Python version: $PYTHON_VERSION"

if [ ! -d "$VENV_DIR" ]; then
    echo "Creating virtual environment..."
    python3 -m venv "$VENV_DIR"
else
    echo "Virtual environment already exists"
fi

echo "Installing dependencies..."
"$VENV_DIR/bin/pip" install --upgrade pip -q
"$VENV_DIR/bin/pip" install -r "$SKILL_DIR/requirements.txt" -q

chmod +x "$SKILL_DIR/scripts/bd_search.py" 2>/dev/null || true

# --- Bright Data CLI ---
find_cli() {
    command -v brightdata 2>/dev/null || command -v bdata 2>/dev/null
}

CLI_BIN=$(find_cli || true)

if [ -z "$CLI_BIN" ]; then
    echo ""
    echo "Bright Data CLI not found on PATH." >&2
    echo "Install it with:" >&2
    echo "  npm install -g @brightdata/cli" >&2
    echo "  # or:  curl -fsSL https://cli.brightdata.com/install.sh | sh" >&2
    echo "" >&2
    echo "Then re-run this setup script." >&2
    exit 1
fi

echo "Bright Data CLI: $CLI_BIN ($("$CLI_BIN" --version 2>/dev/null || echo '?'))"

validate_cli() {
    echo ""
    echo "Testing Bright Data CLI with a live search..."
    local out code
    out=$("$VENV_DIR/bin/python" "$SKILL_DIR/scripts/bd_search.py" "brightdata setup test" -m general -c 1 2>&1 >/dev/null) && code=0 || code=$?
    if [ "$code" = 0 ]; then
        echo "Bright Data CLI OK."
        return 0
    fi
    echo "Validation failed (exit $code):" >&2
    echo "  $out" >&2
    case "$code" in
        2) echo "  → authentication / quota error. Run \`$CLI_BIN login\` (or \`./setup.sh --reset\`) to re-authenticate." >&2 ;;
        *) echo "  → unexpected failure. Check your Bright Data dashboard and CLI install." >&2 ;;
    esac
    return "$code"
}

if [ "$NO_PROMPT" = 1 ]; then
    echo ""
    echo "Skipping CLI auth check (--no-prompt). Authenticate manually with: $CLI_BIN login"
elif [ "$RESET" = 1 ]; then
    echo ""
    echo "--reset specified. Launching \`$CLI_BIN login\`..."
    "$CLI_BIN" login
    validate_cli || {
        echo "Login completed but validation still fails. Investigate above output." >&2
        exit 1
    }
else
    if ! validate_cli; then
        echo ""
        read -r -p "Run \`$CLI_BIN login\` now? (Y/n): " do_login
        if [[ ! "$do_login" =~ ^[Nn]$ ]]; then
            "$CLI_BIN" login
            validate_cli || exit 1
        else
            echo "Skipping login. Re-run ./setup.sh --reset when you're ready." >&2
            exit 1
        fi
    fi
fi

echo ""
echo "=== Setup Complete ==="
echo "Virtual environment: $VENV_DIR"
echo "Bright Data CLI:     $CLI_BIN"
echo ""
echo "Quick test:"
echo "  $VENV_DIR/bin/python $SKILL_DIR/scripts/bd_search.py \"ollama local llm\" -m general --json -c 5"
