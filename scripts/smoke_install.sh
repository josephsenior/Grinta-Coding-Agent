#!/usr/bin/env bash
# Backward-compatible entrypoint — implementation lives in scripts/smoke/
exec "$(cd "$(dirname "$0")" && pwd)/smoke/smoke_install.sh" "$@"
