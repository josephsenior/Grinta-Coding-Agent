#!/usr/bin/env bash
# WSL2 layout smoke — run inside Ubuntu on WSL2 (not GitHub ubuntu-latest).
# Verifies doctor WSL checks and layout classification.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

if [[ -z "${WSL_DISTRO_NAME:-}" ]]; then
    echo "SKIP: not running inside WSL (WSL_DISTRO_NAME unset)"
    exit 0
fi

echo "WSL2 smoke: distro=${WSL_DISTRO_NAME:-unknown} repo=${ROOT}"

uv run python - <<'PY'
from pathlib import Path

from backend.cli.doctor.checks import collect_wsl_checks
from backend.core.wsl import WslLayout, classify_wsl_layout, is_wsl_runtime

assert is_wsl_runtime(), "expected WSL runtime"

layout = classify_wsl_layout(workspace=Path.cwd(), repo_root=Path.cwd())
print(f"layout={layout.value}")

checks = collect_wsl_checks(workspace=Path.cwd())
for check in checks:
    mark = "ok" if check.ok else "WARN"
    print(f"  [{mark}] {check.name}: {check.detail}")

if layout in {WslLayout.REPO_ON_DRVFS, WslLayout.BOTH_ON_DRVFS}:
    raise SystemExit(
        "FAIL: repo on /mnt/* — clone to ~/Grinta (see docs/QUICK_START.md#wsl-ubuntu)"
    )

print("WSL2 layout smoke passed")
PY

uv run python -m backend.cli.entry doctor
