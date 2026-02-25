"""Structured test-runner tool for the Orchestrator agent.

Instead of having the agent parse thousands of lines of raw pytest output,
this tool runs the test suite and returns a compact JSON summary of
``{passed, failed, errors, all_passed, failed_tests}`` followed by the tail
of the captured output.

The runner script is base64-encoded into the CmdRunAction command to avoid
any shell-quoting issues with special characters.
"""

from __future__ import annotations

import base64

from backend.core.constants import RUN_TESTS_TOOL_NAME
from backend.engines.orchestrator.contracts import ChatCompletionToolParam
from backend.engines.orchestrator.tools.common import create_tool_definition
from backend.events.action import CmdRunAction

# ---------------------------------------------------------------------------
# Runner script (base64-encoded at import time)
# ---------------------------------------------------------------------------

_RUNNER = """\
import subprocess, sys, json, re, os

filter_args = sys.argv[1:]
args = [sys.executable, "-m", "pytest", "--tb=short", "--no-header", "-v"] + filter_args
r = subprocess.run(args, capture_output=True, text=True)
out = r.stdout + r.stderr

failed_tests = []
for m in re.finditer(r"^FAILED (.+?) - (.+)$", out, re.M):
    failed_tests.append({"test": m.group(1).strip(), "error": m.group(2).strip()})
for m in re.finditer(r"^ERROR collecting (.+)$", out, re.M):
    failed_tests.append({"test": m.group(1).strip(), "error": "collection error"})

pm = re.search(r"(\\d+) passed", out)
fm = re.search(r"(\\d+) failed", out)
em = re.search(r"(\\d+) error", out)
wm = re.search(r"(\\d+) warning", out)

result = {
    "passed": int(pm.group(1)) if pm else 0,
    "failed": int(fm.group(1)) if fm else 0,
    "collection_errors": int(em.group(1)) if em else 0,
    "warnings": int(wm.group(1)) if wm else 0,
    "all_passed": r.returncode == 0,
    "failed_tests": failed_tests,
}

print("=== TEST RESULTS ===")
print(json.dumps(result, indent=2))
if out.strip():
    tail = out[-3000:] if len(out) > 3000 else out
    print("\\n=== OUTPUT ===")
    print(tail)
"""

_RUNNER_B64: str = base64.b64encode(_RUNNER.encode()).decode()


# ---------------------------------------------------------------------------
# Tool definition
# ---------------------------------------------------------------------------

_DESCRIPTION = (
    "Run the project's test suite (pytest) and return a structured summary.\n\n"
    "Returns JSON containing:\n"
    "  - passed / failed / collection_errors (counts)\n"
    "  - all_passed (bool)\n"
    "  - failed_tests: [{test, error}] (one entry per failing test)\n\n"
    "Followed by the tail of the pytest output.\n\n"
    "Use the `filter` parameter to run a subset, e.g. 'tests/unit/auth' or "
    "'tests/unit/auth.py::test_login'."
)


def create_run_tests_tool() -> ChatCompletionToolParam:
    """Create the structured test-runner tool definition."""
    return create_tool_definition(
        name=RUN_TESTS_TOOL_NAME,
        description=_DESCRIPTION,
        properties={
            "filter": {
                "type": "string",
                "description": (
                    "Optional pytest node-id or path filter, e.g. 'tests/unit' or "
                    "'tests/unit/test_auth.py::test_login'. "
                    "Omit to run the full test suite."
                ),
            },
            "extra_flags": {
                "type": "string",
                "description": (
                    "Optional extra pytest flags, e.g. '-x' (stop on first failure) "
                    "or '--lf' (rerun last failures). Space-separated."
                ),
            },
        },
        required=[],
    )


# ---------------------------------------------------------------------------
# Action builder
# ---------------------------------------------------------------------------

def build_run_tests_action(filter_str: str = "", extra_flags: str = "") -> CmdRunAction:
    """Return a CmdRunAction that runs pytest and prints structured results."""
    extra_args = []
    if filter_str.strip():
        extra_args.append(filter_str.strip())
    if extra_flags.strip():
        extra_args.extend(extra_flags.split())

    # Pass extra args as argv to the runner script
    argv_part = " ".join(f'"{a}"' for a in extra_args) if extra_args else ""
    cmd = f'python -c "import base64,sys;exec(base64.b64decode(b\'{_RUNNER_B64}\').decode())" {argv_part}'.rstrip()

    filter_label = filter_str.strip() or "all tests"
    return CmdRunAction(command=cmd, thought=f"[RUN TESTS] running {filter_label}")
