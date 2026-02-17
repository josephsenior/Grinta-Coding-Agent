#!/usr/bin/env bash
# ============================================
# FORGE - Quick Start Script (Unix/macOS/WSL)
# ============================================
set -e

# Colors
GREEN='\033[0;32m'
CYAN='\033[0;36m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${CYAN}🚀 Starting Forge Setup...${NC}"

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

# Check for Poetry
if ! command -v poetry &> /dev/null; then
    echo -e "${YELLOW}📦 Poetry not found. Installing...${NC}"
    curl -sSL https://install.python-poetry.org | python3 -
    export PATH="$HOME/.local/bin:$PATH"
fi
echo -e "${GREEN}✅ Poetry found!${NC}"

# Step 1: Configuration
if [ ! -f "config.toml" ]; then
    echo -e "${CYAN}📝 Creating config.toml from template...${NC}"
    cp config.template.toml config.toml
fi

# Step 2: Install dependencies
echo -e "${YELLOW}📦 Step 2: Installing dependencies...${NC}"
poetry install

# Step 3: Auto-discover local models
echo -e "${YELLOW}🤖 Step 3: Discovering local models (Ollama/LM Studio/vLLM)...${NC}"
poetry run python3 -m backend.llm.discover_models aliases
echo -e "${GREEN}✅ Model discovery complete.${NC}"

echo -e "\n${GREEN}✅ Forge is ready!${NC}"
echo -e "${CYAN}💡 To start Forge:${NC}"
echo -e "   1. Start the server: ${YELLOW}poetry run forge serve${NC}"
echo -e "   2. Start the TUI:    ${YELLOW}poetry run forge-tui${NC}"
echo -e "\nOr just run: ${CYAN}make run${NC}"
