#!/usr/bin/env bash
# Run Grinta from your *project* directory (dev / uv run workflow).
# uv --directory resets cwd to the Grinta clone; this pins workspace to $PWD first.
set -e
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
export GRINTA_INVOCATION_CWD="$PWD"
exec uv run --directory "$ROOT" grinta "$@"
