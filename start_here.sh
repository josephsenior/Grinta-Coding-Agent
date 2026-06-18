#!/usr/bin/env bash
# Backward-compatible entrypoint — implementation lives in scripts/launch/
exec "$(cd "$(dirname "$0")" && pwd)/scripts/launch/start_here.sh" "$@"
