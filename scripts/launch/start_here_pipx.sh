#!/usr/bin/env bash
# ============================================
# GRINTA - Quick Start (pipx / installed CLI)
# ============================================
# For users who installed with: pipx install grinta-ai
# Mirrors scripts/launch/start_here.sh without uv or source checkout steps.

set -e

GREEN='\033[0;32m'
CYAN='\033[0;36m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
DIM='\033[0;2m'
NC='\033[0m'

echo -e "${CYAN}Starting Grinta (pipx install)...${NC}"

if [[ -n "${WSL_DISTRO_NAME:-}" ]]; then
    if pwd | grep -q '^/mnt/'; then
        echo -e "${YELLOW}WSL2: running from a Windows mount. Prefer: cd ~/... before grinta.${NC}"
        echo -e "${YELLOW}      Official layout: pipx install inside Ubuntu; repo on ~/Grinta; project on /mnt/c OK.${NC}"
        echo -e "${YELLOW}      See docs/QUICK_START.md#wsl-ubuntu${NC}"
        echo ""
    fi
fi

echo -e "${YELLOW}Step 0: Pre-flight checks...${NC}"

if ! command -v grinta &> /dev/null; then
    echo -e "${RED}'grinta' not found on PATH.${NC}"
    echo -e "${YELLOW}Install with: pipx install grinta-ai${NC}"
    exit 1
fi
echo -e "${GREEN}grinta found: $(command -v grinta)${NC}"

GRINTA_BIN="$(command -v grinta)"
GRINTA_DIR="$(cd "$(dirname "$GRINTA_BIN")" && pwd)"
PYTHON="$GRINTA_DIR/python"
if [[ -x "$PYTHON" ]]; then
    if "$PYTHON" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 12) else 1)'; then
        echo -e "${GREEN}Python version ok (pipx venv): $("$PYTHON" --version)${NC}"
    else
        echo -e "${YELLOW}Expected Python 3.12+ in pipx venv. Found: $("$PYTHON" --version)${NC}"
    fi
else
    echo -e "${YELLOW}Could not locate pipx venv python; skipping version probe.${NC}"
fi

echo ""
echo -e "${DIM}Note: Grinta bundles ripgrep. Git and language servers are optional${NC}"
echo -e "${DIM}machine tools (not Grinta dependencies) that unlock more workflow features.${NC}"
echo ""

echo -e "${YELLOW}Step 1: Skipping dependency sync (managed by pipx).${NC}"
echo -e "${GREEN}Using installed grinta-ai package.${NC}"

echo -e "${YELLOW}Step 1.5: Checking local model servers (Ollama/LM Studio/vLLM)...${NC}"
if [[ -x "$PYTHON" ]]; then
    "$PYTHON" -m backend.inference.discover_models status || \
        echo -e "${YELLOW}Local model status check failed; continuing. grinta init will also probe local servers.${NC}"
else
    echo -e "${YELLOW}Skipping local model status (pipx python not found).${NC}"
fi

if [[ -n "${APP_ROOT:-}" ]]; then
    SETTINGS_PATH="${APP_ROOT}/settings.json"
else
    SETTINGS_PATH="${HOME}/.grinta/settings.json"
fi

if [[ ! -f "$SETTINGS_PATH" ]]; then
    echo -e "${YELLOW}Step 1.75: No settings.json found. Starting first-run wizard...${NC}"
    echo -e "${DIM}         Expected path: ${SETTINGS_PATH}${NC}"
    grinta init
fi

echo -e "\n${GREEN}Launching Grinta CLI...${NC}"
echo -e "${CYAN}Runtime state will be stored under ~/.grinta/workspaces/<id>/storage.${NC}"
echo ""

grinta
