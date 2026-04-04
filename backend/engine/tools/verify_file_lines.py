"""verify_file_lines tool — validate the agent's mental model of a file before editing.

After condensation or many edits, the LLM's understanding of a file's current
state can drift.  This tool lets the agent cheaply verify specific assertions
about file contents without reading the entire file, preventing stale-model
edit failures (the #1 cause of failed replace_text operations).

Usage examples:
  verify_file_lines(path="src/main.py", assertions=[
      {"line": 42, "contains": "def process_request"},
      {"line": 100, "contains": "return response"}
  ])
"""

from __future__ import annotations

import os

from backend.engine.contracts import ChatCompletionToolParam
from backend.engine.tools.common import create_tool_definition
from backend.ledger.action.agent import AgentThinkAction

VERIFY_FILE_LINES_TOOL_NAME = 'verify_file_lines'

_DESCRIPTION = (
    'Validate file contents before editing by checking line assertions (line number + expected substring). '
    'Returns PASS/FAIL per assertion. Use after condensation or many edits to catch stale-model errors.'
)


def create_verify_file_lines_tool() -> ChatCompletionToolParam:
    """Create the verify_file_lines tool definition."""
    return create_tool_definition(
        name=VERIFY_FILE_LINES_TOOL_NAME,
        description=_DESCRIPTION,
        properties={
            'path': {
                'type': 'string',
                'description': 'Path to the file to verify.',
            },
            'line_checks': {
                'type': 'string',
                'description': (
                    "Pipe-separated list of 'line_num:expected_substring' assertions. "
                    "Example: '42:def process_request|100:return response|1:import os'"
                ),
            },
        },
        required=['path', 'line_checks'],
    )


def _parse_verify_assertions(line_checks: str) -> list[tuple[int, str]]:
    """Parse line_checks into [(line_num, expected), ...]. Returns empty list on parse failure."""
    assertions = []
    for check in line_checks.split('|'):
        check = check.strip()
        if ':' not in check:
            continue
        parts = check.split(':', 1)
        try:
            assertions.append((int(parts[0].strip()), parts[1].strip()))
        except (ValueError, IndexError):
            continue
    return assertions


def _run_verify_assertions(
    lines: list[str], assertions: list[tuple[int, str]]
) -> tuple[list[str], bool]:
    """Run assertions. Returns (results, all_passed)."""
    results: list[str] = []
    all_passed = True
    for line_num, expected in assertions:
        if line_num < 1 or line_num > len(lines):
            results.append(
                f'  FAIL line {line_num}: out of range (file has {len(lines)} lines)'
            )
            all_passed = False
        elif expected in lines[line_num - 1].rstrip('\n\r'):
            results.append(f"  PASS line {line_num}: contains '{expected}'")
        else:
            results.append(
                f"  FAIL line {line_num}: expected '{expected}' but got: '{lines[line_num - 1][:120]}'"
            )
            all_passed = False
    return (results, all_passed)


def build_verify_file_lines_action(arguments: dict) -> AgentThinkAction:
    """Execute verify_file_lines and return a think action with pass/fail results."""
    path = arguments.get('path', '')
    line_checks = arguments.get('line_checks', '')

    if not path:
        return AgentThinkAction(thought="[VERIFY_FILE_LINES] 'path' is required.")
    if not line_checks:
        return AgentThinkAction(
            thought="[VERIFY_FILE_LINES] 'line_checks' is required (format: 'line:substring|line:substring')."
        )
    if not os.path.isfile(path):
        return AgentThinkAction(
            thought=f'[VERIFY_FILE_LINES] FAIL — file not found: {path}'
        )

    try:
        with open(path, encoding='utf-8', errors='replace') as f:
            lines = f.readlines()
    except OSError as exc:
        return AgentThinkAction(
            thought=f'[VERIFY_FILE_LINES] FAIL — cannot read {path}: {exc}'
        )

    assertions = _parse_verify_assertions(line_checks)
    if not assertions:
        return AgentThinkAction(
            thought="[VERIFY_FILE_LINES] No valid assertions parsed. Format: 'line_num:expected_text|line_num:expected_text'"
        )

    results, all_passed = _run_verify_assertions(lines, assertions)
    status = 'ALL PASSED' if all_passed else 'SOME FAILED'
    header = f'[VERIFY_FILE_LINES] {path} — {status} ({len(assertions)} checks)'
    return AgentThinkAction(thought=f'{header}\n' + '\n'.join(results))
