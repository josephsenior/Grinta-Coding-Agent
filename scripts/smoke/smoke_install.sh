#!/usr/bin/env bash
# Clean-room install smoke-test for Grinta.
#
# Validates that `pip install grinta` and the optional extras work on a
# fresh Python environment. Run inside a Docker container or a throwaway venv.
#
# Usage:
#   ./scripts/smoke_install.sh                 # base install only
#   ./scripts/smoke_install.sh rag             # base + [rag]
#   ./scripts/smoke_install.sh rag browser     # base + multiple extras
#   ./scripts/smoke_install.sh all             # everything
set -euo pipefail

EXTRAS="${*:-}"
WHEEL_DIR="${WHEEL_DIR:-./dist}"

if [ -d "$WHEEL_DIR" ] && ls "$WHEEL_DIR"/*.whl >/dev/null 2>&1; then
    PKG_SPEC="$(ls "$WHEEL_DIR"/grinta_ai-*.whl | head -n1)"
    echo "==> Using local wheel: $PKG_SPEC"
else
    PKG_SPEC="grinta"
    echo "==> Using PyPI: $PKG_SPEC"
fi

if [ -n "$EXTRAS" ]; then
    EXTRA_SPEC="[$(echo "$EXTRAS" | tr ' ' ',')]"
else
    EXTRA_SPEC=""
fi

echo "==> Creating fresh venv at /tmp/grinta-smoke-venv"
rm -rf /tmp/grinta-smoke-venv
python3 -m venv /tmp/grinta-smoke-venv
# shellcheck disable=SC1091
. /tmp/grinta-smoke-venv/bin/activate

echo "==> Installing: $PKG_SPEC$EXTRA_SPEC"
pip install --upgrade pip --quiet
pip install "$PKG_SPEC$EXTRA_SPEC"

echo
echo "==> Disk size of installed packages"
du -sh /tmp/grinta-smoke-venv/lib

echo
echo "==> Smoke-test: import + --help"
python -c "import backend; print('backend version:', backend.__version__ if hasattr(backend, '__version__') else 'unknown')"
python -m backend.cli.entry --help | head -n 5

echo
echo "==> Smoke-test: optional-imports verifier"
python backend/scripts/verify/verify_optional_imports.py

echo
echo "==> Smoke-test: init rejects non-interactive stdin"
SMOKE_APP_ROOT="/tmp/grinta-smoke-app"
rm -rf "$SMOKE_APP_ROOT"
mkdir -p "$SMOKE_APP_ROOT"
export APP_ROOT="$SMOKE_APP_ROOT"
set +e
printf '' | python -m backend.cli.entry init >/dev/null 2>&1
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

echo
echo "==> Smoke-test: stub CLI task (deterministic LLM, no live API)"
repo_root="$(cd "$(dirname "$0")/../.." && pwd)"
chmod +x "$repo_root/scripts/smoke/run_stub_cli_task.sh"
"$repo_root/scripts/smoke/run_stub_cli_task.sh" python "$repo_root"

echo
echo "==> Done. Extras installed: ${EXTRAS:-(none)}"
deactivate
