#!/usr/bin/env bash
# ============================================
# GRINTA - Quick Start Script (Unix/macOS/WSL)
# ============================================
set -e

# Colors
GREEN='\033[0;32m'
CYAN='\033[0;36m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${CYAN}Starting Grinta Setup...${NC}"

# Step 0: Pre-flight checks
echo -e "${YELLOW}Step 0: Pre-flight checks...${NC}"

# Check Python version (no external bc dependency)
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}python3 not found.${NC}"
    exit 1
fi

if ! python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 12) else 1)'; then
    PYTHON_VERSION=$(python3 -c 'import sys; print(".".join(map(str, sys.version_info[:2])))')
    echo -e "${RED}Python 3.12+ required. Found: ${PYTHON_VERSION}${NC}"
    exit 1
fi
PYTHON_VERSION=$(python3 -c 'import sys; print(".".join(map(str, sys.version_info[:2])))')
echo -e "${GREEN}Python version ok: ${PYTHON_VERSION}${NC}"

# Check for uv
if ! command -v uv &> /dev/null; then
    echo -e "${YELLOW}uv not found. Installing...${NC}"
    curl -LsSf https://astral.sh/uv/install.sh | sh
    # shellcheck disable=SC1091
    source "$HOME/.cargo/env" 2>/dev/null || true
    export PATH="$HOME/.local/bin:$PATH"
fi
echo -e "${GREEN}uv found!${NC}"

# Step 1: Install dependencies
echo -e "${YELLOW}Step 1: Syncing dependencies (dev-test profile)...${NC}"
python3 scripts/bootstrap_env.py dev-test

# Step 1.5: Report local model provider status (optional; does not modify settings)
echo -e "${YELLOW}Step 1.5: Checking local model servers (Ollama/LM Studio/vLLM)...${NC}"
uv run python -m backend.inference.discover_models status || \
    echo -e "${YELLOW}Local model status check failed; continuing.${NC}"

# Step 1.75: First-run configuration
if [ ! -f "settings.json" ]; then
    echo -e "${YELLOW}Step 1.75: No settings.json found. Starting first-run wizard...${NC}"
    uv run python -m backend.cli.entry init
fi

echo -e "\n${GREEN}Setup complete! Launching Grinta CLI...${NC}"
echo -e "${CYAN}   Runtime state will be stored under ~/.grinta/workspaces/<id>/storage.${NC}"
echo ""

uv run python -m backend.cli.entry
