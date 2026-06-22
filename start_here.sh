#!/usr/bin/env bash
# Grinta unified Unix launcher (source checkout or pipx install).
#
# Auto-selects the flow:
#   - Source checkout (uv sync + uv run) when pyproject.toml is present
#   - pipx install (grinta on PATH) otherwise
#
# Override:
#   ./start_here.sh --pipx     # force pipx flow from a source checkout
#   ./start_here.sh --source   # force source flow
#
# Implementation: scripts/launch/

set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
LAUNCH="$ROOT/scripts/launch"

use_pipx=""
args=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --pipx)
      use_pipx=1
      shift
      ;;
    --source)
      use_pipx=0
      shift
      ;;
    *)
      args+=("$1")
      shift
      ;;
  esac
done

if [[ -z "$use_pipx" ]]; then
  if [[ -f "$ROOT/pyproject.toml" ]]; then
    use_pipx=0
  else
    use_pipx=1
  fi
fi

if [[ "$use_pipx" -eq 1 ]]; then
  exec "$LAUNCH/start_here_pipx.sh" "${args[@]}"
else
  exec "$LAUNCH/start_here.sh" "${args[@]}"
fi
