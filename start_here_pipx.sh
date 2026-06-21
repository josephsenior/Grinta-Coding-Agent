#!/usr/bin/env bash
# Backward-compatible entrypoint for pipx installs — implementation in scripts/launch/
ROOT="$(cd "$(dirname "$0")" && pwd)"
exec "$ROOT/scripts/launch/start_here_pipx.sh" "$@"
