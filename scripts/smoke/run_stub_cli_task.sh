#!/usr/bin/env bash
# Run one piped CLI task with the deterministic LLM stub (no live API).
#
# Usage:
#   ./scripts/smoke/run_stub_cli_task.sh /path/to/python /path/to/repo
#   UV_RUN=1 ./scripts/smoke/run_stub_cli_task.sh ignored /path/to/repo
set -euo pipefail

PYTHON="${1:-python3}"
REPO_ROOT="${2:?repository root required}"

SMOKE_ROOT="${SMOKE_ROOT:-/tmp/grinta-stub-task-smoke}"
APP_ROOT="${APP_ROOT:-$SMOKE_ROOT/app}"
PROJECT_ROOT="${PROJECT_ROOT:-$SMOKE_ROOT/project}"
STUB_RUNNER="$REPO_ROOT/scripts/smoke/run_cli_with_stub.py"

rm -rf "$SMOKE_ROOT"
mkdir -p "$APP_ROOT" "$PROJECT_ROOT"
printf 'CLI smoke README target\n' >"$PROJECT_ROOT/README.md"

cat >"$APP_ROOT/settings.json" <<'JSON'
{
  "llm_provider": "openai",
  "llm_model": "openai/gpt-4.1",
  "llm_api_key": "${LLM_API_KEY}",
  "llm_base_url": "",
  "agent": {
    "Orchestrator": {
      "autonomy_level": "balanced"
    }
  },
  "security": {
    "execution_profile": "hardened_local",
    "enforce_security": true
  }
}
JSON

export APP_ROOT
export LLM_API_KEY="${LLM_API_KEY:-sk-smoke-stub-task}"
export LLM_MODEL="${LLM_MODEL:-openai/gpt-4.1}"
export GRINTA_NO_SPLASH=1
export GRINTA_SKIP_STARTUP_HEALTH_CHECK=1
export LOG_TO_FILE=false
export PYTHONUTF8=1
export PYTHONPATH="$REPO_ROOT${PYTHONPATH:+:$PYTHONPATH}"

run_cli() {
  if [ "${UV_RUN:-0}" = 1 ]; then
    uv run python "$STUB_RUNNER" --project "$PROJECT_ROOT" --no-splash "$@"
  else
    "$PYTHON" "$STUB_RUNNER" --project "$PROJECT_ROOT" --no-splash "$@"
  fi
}

output="$(
  printf 'Summarize README.md in one sentence.\n' | run_cli 2>&1
)"
rc=$?

if [ "$rc" -ne 0 ]; then
  echo "$output"
  echo "Stub CLI task failed with exit code $rc"
  exit "$rc"
fi

case "$output" in
  *'Agent completed'*) ;;
  *)
    echo "$output"
    echo 'Stub CLI task did not report agent completion'
    exit 1
    ;;
esac

echo '==> Stub CLI task smoke passed'
