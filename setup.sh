#!/bin/bash
# Set up deep-research skill: Python venv + Bright Data credentials + live validation.
#
# Usage:
#   ./setup.sh              # Provision venv. Prompt for credentials if not yet set.
#   ./setup.sh --reset      # Force re-entry of credentials (overwrite existing).
#   ./setup.sh --no-prompt  # Provision venv + template only. No interactive prompts.
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$SCRIPT_DIR"
VENV_DIR="$SKILL_DIR/.venv"
CONFIG_DIR="$HOME/.deep-research"
CONFIG_FILE="$CONFIG_DIR/config.env"

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

# --- Credentials ---
mkdir -p "$CONFIG_DIR"
chmod 700 "$CONFIG_DIR"

write_template() {
    cat > "$CONFIG_FILE" <<'CRED_EOF'
# Bright Data credentials for the deep-research skill.
# Get these from https://brightdata.com/cp/zones after creating your zones.

BRIGHTDATA_API_TOKEN=
BD_SERP_ZONE=
BD_UNLOCKER_ZONE=

# Optional: default country code (ISO-3166 alpha-2) for SERP geolocation, e.g. gb, us, de.
# BD_COUNTRY=
CRED_EOF
    chmod 600 "$CONFIG_FILE"
}

# Read a single non-empty KEY=VALUE from the config file. Strips surrounding quotes.
read_config_value() {
    local key="$1"
    [ -f "$CONFIG_FILE" ] || return 1
    local val
    val=$(grep -E "^${key}=" "$CONFIG_FILE" | tail -n1 | sed -E "s/^${key}=//; s/^['\"]//; s/['\"]\$//")
    [ -n "$val" ] && printf '%s' "$val"
}

prompt_credentials() {
    local current_token current_serp current_unlock current_country
    current_token=$(read_config_value BRIGHTDATA_API_TOKEN || true)
    current_serp=$(read_config_value BD_SERP_ZONE || true)
    current_unlock=$(read_config_value BD_UNLOCKER_ZONE || true)
    current_country=$(read_config_value BD_COUNTRY || true)

    echo ""
    echo "Enter your Bright Data credentials."
    echo "Get them from https://brightdata.com/cp/zones — you need one SERP API zone and one Web Unlocker zone."
    echo "Press Enter to keep the existing value shown in [brackets]."
    echo ""

    local token serp unlock country
    if [ -n "$current_token" ]; then
        read -r -p "API token [${current_token:0:6}…${current_token: -4}]: " token
    else
        read -r -p "API token: " token
    fi
    token="${token:-$current_token}"

    read -r -p "SERP API zone name${current_serp:+ [$current_serp]}: " serp
    serp="${serp:-$current_serp}"

    read -r -p "Web Unlocker zone name${current_unlock:+ [$current_unlock]}: " unlock
    unlock="${unlock:-$current_unlock}"

    read -r -p "Default country code (optional)${current_country:+ [$current_country]}: " country
    country="${country:-$current_country}"

    if [ -z "$token" ] || [ -z "$serp" ] || [ -z "$unlock" ]; then
        echo "Error: API token, SERP zone and Web Unlocker zone are all required." >&2
        return 1
    fi

    {
        echo "# Bright Data credentials for the deep-research skill."
        echo "# Edit with: ~/.claude/skills/deep-research/setup.sh --reset"
        echo ""
        echo "BRIGHTDATA_API_TOKEN=$token"
        echo "BD_SERP_ZONE=$serp"
        echo "BD_UNLOCKER_ZONE=$unlock"
        if [ -n "$country" ]; then
            echo "BD_COUNTRY=$country"
        else
            echo "# BD_COUNTRY="
        fi
    } > "$CONFIG_FILE"
    chmod 600 "$CONFIG_FILE"
    echo ""
    echo "Saved credentials to $CONFIG_FILE"
}

# Returns 0 if all three required keys are present and non-empty.
config_has_credentials() {
    [ -f "$CONFIG_FILE" ] || return 1
    [ -n "$(read_config_value BRIGHTDATA_API_TOKEN || true)" ] && \
    [ -n "$(read_config_value BD_SERP_ZONE || true)" ] && \
    [ -n "$(read_config_value BD_UNLOCKER_ZONE || true)" ]
}

validate_credentials() {
    echo ""
    echo "Testing credentials against Bright Data SERP API..."
    local out code
    out=$("$VENV_DIR/bin/python" "$SKILL_DIR/scripts/bd_search.py" "brightdata setup test" -m general -c 1 2>&1 >/dev/null) && code=0 || code=$?
    if [ "$code" = 0 ]; then
        echo "Credentials OK."
        return 0
    fi
    echo "Validation failed (exit $code):" >&2
    echo "  $out" >&2
    case "$code" in
        2) echo "  → authentication / quota error. Check token + zone names in $CONFIG_FILE" >&2 ;;
        *) echo "  → check your credentials and Bright Data dashboard" >&2 ;;
    esac
    return "$code"
}

if [ "$NO_PROMPT" = 1 ]; then
    if [ ! -f "$CONFIG_FILE" ]; then
        write_template
        echo ""
        echo "Created credentials template: $CONFIG_FILE"
        echo "Edit it (or rerun with ./setup.sh) before running deep research."
    else
        chmod 600 "$CONFIG_FILE"
        echo "Existing credentials at $CONFIG_FILE (left unchanged — non-interactive run)."
    fi
elif [ "$RESET" = 1 ] || ! config_has_credentials; then
    if [ "$RESET" = 1 ] && config_has_credentials; then
        echo ""
        echo "--reset specified. Re-entering credentials."
    fi
    if ! prompt_credentials; then
        echo "Setup did not complete. Run ./setup.sh again to retry." >&2
        exit 1
    fi
    if ! validate_credentials; then
        echo ""
        read -r -p "Save credentials anyway? (y/N): " save_anyway
        if [[ ! "$save_anyway" =~ ^[Yy]$ ]]; then
            write_template
            echo "Credentials cleared. Run ./setup.sh --reset to try again." >&2
            exit 1
        fi
    fi
else
    chmod 600 "$CONFIG_FILE"
    echo ""
    echo "Existing credentials at $CONFIG_FILE"
    if validate_credentials; then
        :
    else
        echo ""
        echo "Run ./setup.sh --reset to re-enter credentials." >&2
    fi
fi

echo ""
echo "=== Setup Complete ==="
echo "Virtual environment: $VENV_DIR"
echo "Credentials:         $CONFIG_FILE"
echo ""
echo "Quick test:"
echo "  $VENV_DIR/bin/python $SKILL_DIR/scripts/bd_search.py \"ollama local llm\" -m general --json -c 5"
