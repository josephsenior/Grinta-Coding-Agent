#!/usr/bin/env bash
set -euo pipefail

echo "[1/4] Checking uv"
if ! command -v uv >/dev/null 2>&1; then
  echo "uv is required: https://docs.astral.sh/uv/"
  exit 1
fi

echo "[2/4] Syncing dependencies"
uv sync --group dev --group test

echo "[3/4] Running quick unit smoke"
PYTHONPATH=".:${PYTHONPATH:-}" uv run pytest -q backend/tests/unit -k "not integration" --maxfail=1

echo "[4/4] Verifying CLI starts"
uv run python -m backend.cli.entry --help >/dev/null

echo "Contributor bootstrap check passed."
