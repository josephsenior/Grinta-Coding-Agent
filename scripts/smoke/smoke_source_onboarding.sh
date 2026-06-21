#!/usr/bin/env bash
# Automated smoke for the contributor / source-checkout onboarding path.
#
# Validates dependency sync, CLI entry --help, and non-interactive grinta init
# behavior. Interactive init + first task remain manual (see docs/FRESH_MACHINE_ONBOARDING.md).
#
# Usage (from repo root):
#   ./scripts/smoke_source_onboarding.sh
set -euo pipefail

echo "==> Source onboarding smoke: sync base profile"
python3 scripts/bootstrap_env.py base

echo "==> Source onboarding smoke: CLI --help"
uv run python -m backend.cli.entry --help | head -n 5

echo "==> Source onboarding smoke: init rejects non-interactive stdin"
SMOKE_APP_ROOT="/tmp/grinta-source-smoke-app"
rm -rf "$SMOKE_APP_ROOT"
mkdir -p "$SMOKE_APP_ROOT"
export APP_ROOT="$SMOKE_APP_ROOT"
set +e
printf '' | uv run python -m backend.cli.entry init >/dev/null 2>&1
init_rc=$?
set -e
if [ "$init_rc" -ne 3 ]; then
  echo "Expected grinta init exit 3 without TTY, got $init_rc"
  exit 1
fi
if [ -f "$SMOKE_APP_ROOT/settings.json" ]; then
  echo "grinta init should not write settings.json without a TTY"
  exit 1
fi
unset APP_ROOT

echo "==> Source onboarding smoke: stub CLI task (deterministic LLM, no live API)"
chmod +x scripts/smoke/run_stub_cli_task.sh
UV_RUN=1 ./scripts/smoke/run_stub_cli_task.sh ignored "$(pwd)"

echo "==> Source onboarding smoke: passed"
