#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

_refresh_uv_path() {
    export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
}

_ensure_uv() {
    _refresh_uv_path
    if command -v uv >/dev/null 2>&1; then
        return 0
    fi
    echo "uv not found. Installing via Astral installer..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    _refresh_uv_path
    if ! command -v uv >/dev/null 2>&1; then
        echo "uv install finished but 'uv' is still not on PATH."
        echo "Run scripts/launch/start_here.sh or add ~/.local/bin to PATH."
        exit 1
    fi
}

_ensure_python() {
    uv python install 3.12
}

echo "[0/4] Ensuring toolchain"
_ensure_uv
_ensure_python

echo "[1/4] Checking uv"
command -v uv >/dev/null

echo "[2/4] Syncing dependencies"
uv run python scripts/bootstrap_env.py dev-test

echo "[3/4] Running quick unit smoke"
PYTHONPATH=".:${PYTHONPATH:-}" uv run pytest -q backend/tests/unit -k "not integration" --maxfail=1

echo "[4/4] Verifying CLI starts"
uv run python -m backend.cli.entry --help >/dev/null

echo "Contributor bootstrap check passed."
