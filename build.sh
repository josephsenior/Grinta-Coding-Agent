#!/usr/bin/env bash
# Backward-compatible entrypoint — implementation lives in scripts/
exec "$(cd "$(dirname "$0")" && pwd)/scripts/build.sh" "$@"
