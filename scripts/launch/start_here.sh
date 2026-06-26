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
    echo -e "${YELLOW}Note: Grinta is on a Windows drive (${ROOT}).${NC}"
    echo -e "${YELLOW}      For faster setup, clone to Linux home instead:${NC}"
    echo -e "${YELLOW}        git clone ${ROOT} ~/Grinta && cd ~/Grinta && bash start_here.sh${NC}"
    echo -e "${YELLOW}      Logs will still be written under: ${GRINTA_LOG_ROOT}${NC}"
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

# Step 0: Pre-flight checks
echo -e "${YELLOW}Step 0: Pre-flight checks...${NC}"

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

if ! command -v uv &> /dev/null; then
    echo -e "${YELLOW}uv not found. Installing...${NC}"
    curl -LsSf https://astral.sh/uv/install.sh | sh
    # shellcheck disable=SC1091
    source "$HOME/.cargo/env" 2>/dev/null || true
    export PATH="$HOME/.local/bin:$PATH"
fi
echo -e "${GREEN}uv found!${NC}"

echo -e "${YELLOW}Step 1: Syncing dependencies (dev-test profile)...${NC}"
python3 scripts/bootstrap_env.py dev-test

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
