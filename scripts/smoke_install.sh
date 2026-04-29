#!/usr/bin/env bash
# Clean-room install smoke-test for Grinta.
#
# Validates that `pip install grinta-ai` and the optional extras work on a
# fresh Python environment. Run inside a Docker container or a throwaway venv.
#
# Usage:
#   ./scripts/smoke_install.sh                 # base install only
#   ./scripts/smoke_install.sh rag             # base + [rag]
#   ./scripts/smoke_install.sh rag documents   # base + multiple extras
#   ./scripts/smoke_install.sh all             # everything
set -euo pipefail

EXTRAS="${*:-}"
WHEEL_DIR="${WHEEL_DIR:-./dist}"

if [ -d "$WHEEL_DIR" ] && ls "$WHEEL_DIR"/*.whl >/dev/null 2>&1; then
    PKG_SPEC="$(ls "$WHEEL_DIR"/grinta_ai-*.whl | head -n1)"
    echo "==> Using local wheel: $PKG_SPEC"
else
    PKG_SPEC="grinta-ai"
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
echo "==> Done. Extras installed: ${EXTRAS:-(none)}"
deactivate
