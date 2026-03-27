#!/usr/bin/env python3
"""Start the Forge backend server with the canonical local startup flow."""

from pathlib import Path
import sys

project_root = Path(__file__).parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from backend.cli.server_startup import (  # noqa: E402
    build_server_startup_plan,
    ensure_utf8_stdout,
    print_server_startup_preflight,
    record_startup_snapshot,
    run_server_plan,
    validate_storage_contract,
)


if __name__ == "__main__":
    ensure_utf8_stdout()
    plan = build_server_startup_plan(project_root)
    validate_storage_contract()
    record_startup_snapshot(plan)
    print_server_startup_preflight(plan)
    run_server_plan(plan)

