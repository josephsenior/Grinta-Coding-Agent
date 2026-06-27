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

# Run from repository root (this script lives in scripts/launch/)
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

# Logs + settings always live in the Grinta install tree — never in the open project folder.
export GRINTA_REPO_ROOT="$ROOT"
export GRINTA_LOG_ROOT="$ROOT/logs"
mkdir -p "$GRINTA_LOG_ROOT"

if [[ "$ROOT" == /mnt/* ]]; then
    echo -e "${YELLOW}WSL2: Grinta repo is on a Windows drive (${ROOT}).${NC}"
    echo -e "${YELLOW}      Official supported layout: clone repo to Linux home, project may stay on /mnt/c:${NC}"
    echo -e "${YELLOW}        git clone ${ROOT} ~/Grinta && cd ~/Grinta && bash start_here.sh${NC}"
    echo -e "${YELLOW}      See docs/QUICK_START.md#wsl-ubuntu${NC}"
    echo ""
elif [[ -n "${WSL_DISTRO_NAME:-}" ]] && [[ "$ROOT" != /mnt/* ]]; then
    echo -e "${GREEN}WSL2: repo on Linux filesystem (recommended).${NC}"
    if [[ -n "$PROJECT_PATH" ]] && [[ "$PROJECT_PATH" == /mnt/* ]]; then
        echo -e "${GREEN}      Supported split layout: project on Windows mount is OK.${NC}"
    fi
    echo ""
fi

PROJECT_PATH=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        -p|--project)
            PROJECT_PATH="${2:-}"
            shift 2
            ;;
        *)
            if [[ -z "$PROJECT_PATH" ]]; then
                PROJECT_PATH="$1"
            fi
            shift
            ;;
    esac
done

_refresh_uv_path() {
    export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
}

_ensure_uv() {
    _refresh_uv_path
    if command -v uv &> /dev/null; then
        echo -e "${GREEN}uv found: $(command -v uv)${NC}"
        return 0
    fi

    echo -e "${YELLOW}uv not found. Installing via Astral installer...${NC}"
    curl -LsSf https://astral.sh/uv/install.sh | sh
    _refresh_uv_path

    if ! command -v uv &> /dev/null; then
        echo -e "${RED}uv install finished but 'uv' is still not on PATH.${NC}"
        echo -e "${RED}Add ~/.local/bin to PATH, open a new terminal, and rerun start_here.sh${NC}"
        echo -e "${RED}Manual install: https://docs.astral.sh/uv/${NC}"
        exit 1
    fi
    echo -e "${GREEN}uv installed.${NC}"
}

_ensure_python() {
    echo -e "${YELLOW}Ensuring Python 3.12 via uv (no system Python required)...${NC}"
    if ! uv python install 3.12; then
        echo -e "${RED}Failed to install Python 3.12 with uv.${NC}"
        echo -e "${RED}Try manually: uv python install 3.12${NC}"
        echo -e "${RED}Docs: https://docs.astral.sh/uv/guides/install-python/${NC}"
        exit 1
    fi

    PYTHON_VERSION="$(uv run python --version 2>&1 || true)"
    if [[ "$PYTHON_VERSION" =~ Python\ 3\.(1[2-9]|[2-9][0-9]) ]]; then
        echo -e "${GREEN}Python ok (via uv): ${PYTHON_VERSION}${NC}"
        return 0
    fi

    echo -e "${RED}Python 3.12+ required. uv reported: ${PYTHON_VERSION}${NC}"
    exit 1
}

# Step 0: Toolchain (uv + Python managed by uv)
echo -e "${YELLOW}Step 0: Toolchain...${NC}"
_ensure_uv
_ensure_python

echo -e "${YELLOW}Step 1: Syncing dependencies (dev-test profile)...${NC}"
uv run python scripts/bootstrap_env.py dev-test

echo -e "${YELLOW}Step 1.5: Checking local model servers (Ollama/LM Studio/vLLM)...${NC}"
uv run python -m backend.inference.discover_models status || \
    echo -e "${YELLOW}Local model status check failed; continuing.${NC}"

if [ ! -f "settings.json" ]; then
    echo -e "${YELLOW}Step 1.75: No settings.json found. Starting first-run wizard...${NC}"
    uv run python -m backend.cli.entry init
fi

echo -e "${YELLOW}Step 2: Running doctor...${NC}"
if ! uv run python -m backend.cli.entry doctor; then
    echo -e "${RED}Doctor found problems. Fix settings/.env then re-run start_here.sh${NC}"
    echo -e "${CYAN}Logs directory: ${GRINTA_LOG_ROOT}${NC}"
    exit 1
fi

LAUNCH_ARGS=()
if [[ -n "$PROJECT_PATH" ]]; then
    LAUNCH_ARGS=( -p "$PROJECT_PATH" )
    echo -e "${GREEN}Opening workspace: ${PROJECT_PATH}${NC}"
fi

echo ""
echo -e "${GREEN}Setup complete! Launching Grinta...${NC}"
echo -e "${CYAN}   Logs: ${GRINTA_LOG_ROOT}/workspaces/...${NC}"
echo -e "${CYAN}   Session data: ~/.grinta/workspaces/<id>/storage${NC}"
echo ""

uv run python -m backend.cli.entry "${LAUNCH_ARGS[@]}"
