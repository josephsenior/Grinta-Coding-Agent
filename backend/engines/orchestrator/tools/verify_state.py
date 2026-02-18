"""verify_state tool — validate the agent's mental model of a file before editing.

After condensation or many edits, the LLM's understanding of a file's current
state can drift.  This tool lets the agent cheaply verify specific assertions
about file contents without reading the entire file, preventing stale-model
edit failures (the #1 cause of failed str_replace operations).

Usage examples:
  verify_state(path="src/main.py", assertions=[
      {"line": 42, "contains": "def process_request"},
      {"line": 100, "contains": "return response"}
  ])
"""

from __future__ import annotations

import os

from backend.engines.orchestrator.contracts import ChatCompletionToolParam
from backend.engines.orchestrator.tools.common import create_tool_definition
from backend.events.action.agent import AgentThinkAction

VERIFY_STATE_TOOL_NAME = "verify_state"

_DESCRIPTION = (
    "Validate your mental model of a file's current contents before editing. "
    "Pass a file path and a list of assertions (line number + expected substring). "
    "Returns PASS/FAIL for each assertion, helping you catch stale-model errors "
    "before attempting a str_replace that would fail.\n\n"
    "Use this after context condensation or after many edits to confirm "
    "your understanding of the file is still accurate.\n\n"
    "Example: verify_state(path='main.py', line_checks='42:def process|100:return response')"
)


def create_verify_state_tool() -> ChatCompletionToolParam:
    """Create the verify_state tool definition."""
    return create_tool_definition(
        name=VERIFY_STATE_TOOL_NAME,
        description=_DESCRIPTION,
        properties={
            "path": {
                "type": "string",
                "description": "Path to the file to verify.",
            },
            "line_checks": {
                "type": "string",
                "description": (
                    "Pipe-separated list of 'line_num:expected_substring' assertions. "
                    "Example: '42:def process_request|100:return response|1:import os'"
                ),
            },
        },
        required=["path", "line_checks"],
    )


def build_verify_state_action(arguments: dict) -> AgentThinkAction:
    """Execute verify_state and return a think action with pass/fail results."""
    path = arguments.get("path", "")
    line_checks = arguments.get("line_checks", "")

    if not path:
        return AgentThinkAction(
            thought="[VERIFY_STATE] 'path' is required."
        )
    if not line_checks:
        return AgentThinkAction(
            thought="[VERIFY_STATE] 'line_checks' is required (format: 'line:substring|line:substring')."
        )

    if not os.path.isfile(path):
        return AgentThinkAction(
            thought=f"[VERIFY_STATE] FAIL — file not found: {path}"
        )

    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except OSError as exc:
        return AgentThinkAction(
            thought=f"[VERIFY_STATE] FAIL — cannot read {path}: {exc}"
        )

    # Parse assertions
    assertions = []
    for check in line_checks.split("|"):
        check = check.strip()
        if ":" not in check:
            continue
        parts = check.split(":", 1)
        try:
            line_num = int(parts[0].strip())
            expected = parts[1].strip()
            assertions.append((line_num, expected))
        except (ValueError, IndexError):
            continue

    if not assertions:
        return AgentThinkAction(
            thought="[VERIFY_STATE] No valid assertions parsed. Format: 'line_num:expected_text|line_num:expected_text'"
        )

    # Run assertions
    results: list[str] = []
    all_passed = True
    for line_num, expected in assertions:
        if line_num < 1 or line_num > len(lines):
            results.append(f"  FAIL line {line_num}: out of range (file has {len(lines)} lines)")
            all_passed = False
            continue

        actual_line = lines[line_num - 1].rstrip("\n\r")
        if expected in actual_line:
            results.append(f"  PASS line {line_num}: contains '{expected}'")
        else:
            # Show what the line actually contains
            actual_preview = actual_line[:120]
            results.append(f"  FAIL line {line_num}: expected '{expected}' but got: '{actual_preview}'")
            all_passed = False

    status = "ALL PASSED" if all_passed else "SOME FAILED"
    header = f"[VERIFY_STATE] {path} — {status} ({len(assertions)} checks)"
    return AgentThinkAction(thought=f"{header}\n" + "\n".join(results))
