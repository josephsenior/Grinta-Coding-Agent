#!/usr/bin/env bash
# Backward-compatible entrypoint — implementation lives in scripts/docker/
exec "$(cd "$(dirname "$0")" && pwd)/scripts/docker/docker_start.sh" "$@"
