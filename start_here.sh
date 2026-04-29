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

echo -e "${CYAN}🚀 Starting Grinta Setup...${NC}"

# Step 0: Pre-flight checks
echo -e "${YELLOW}🔍 Step 0: Pre-flight checks...${NC}"

# Check Python version
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}❌ python3 not found.${NC}"
    exit 1
fi

PYTHON_VERSION=$(python3 -c 'import sys; print(".".join(map(str, sys.version_info[:2])))')
if [[ $(echo "$PYTHON_VERSION >= 3.12" | bc -l) -eq 0 ]]; then
    echo -e "${RED}❌ Python 3.12+ required. Found: $PYTHON_VERSION${NC}"
    exit 1
fi
echo -e "${GREEN}✅ Python version ok: $PYTHON_VERSION${NC}"

# Check for uv
if ! command -v uv &> /dev/null; then
    echo -e "${YELLOW}📦 uv not found. Installing...${NC}"
    curl -LsSf https://astral.sh/uv/install.sh | sh
    source "$HOME/.cargo/env" 2>/dev/null || true
    export PATH="$HOME/.local/bin:$PATH"
fi
echo -e "${GREEN}✅ uv found!${NC}"

# Step 1: Configuration
if [ ! -f "settings.json" ]; then
    echo -e "${CYAN}📝 No settings.json found. Run uv run python -m backend.cli.entry init after dependencies sync if configuration is needed.${NC}"
fi

# Step 2: Install dependencies
echo -e "${YELLOW}📦 Step 2: Syncing dependencies...${NC}"
uv sync

# Step 3: Auto-discover local models
echo -e "${YELLOW}🤖 Step 3: Discovering local models (Ollama/LM Studio/vLLM)...${NC}"
uv run python3 -m backend.llm.discover_models aliases
echo -e "${GREEN}✅ Model discovery complete.${NC}"

echo -e "\n${GREEN}✅ Setup complete! Launching Grinta CLI...${NC}"
echo -e "${CYAN}   Runtime state will be stored under ~/.grinta/workspaces/<id>/storage.${NC}"
echo ""

uv run python -m backend.cli.entry
