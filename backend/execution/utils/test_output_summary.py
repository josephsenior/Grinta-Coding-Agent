"""Shared parsing of test-runner stdout for truncation and review.

Patterns are duplicated in a single module so ``truncate_cmd_output`` and
the test-output summarizers stay aligned and regressions are caught by one test suite.
"""

from __future__ import annotations

import re

# (pattern, framework label) — used for "does this blob look like test output?"
TEST_FRAMEWORK_PATTERNS: list[tuple[str, str]] = [
    (r'=+\s*\d+\s+(passed|failed|error|skipped)', 'pytest'),
    (r'^Tests:\s+\d+\s+failed,\s+\d+\s+passed,\s+\d+\s+total', 'jest'),
    (r'^test result:\s+(ok|FAILED)\.', 'cargo'),
    (r'^(ok|FAIL)\s+\S+\s+\d+(\.\d+)?s$', 'go'),
    # unittest: "Ran 42 tests in 1.234s"
    (r'^Ran\s+\d+\s+tests?\s+in\s+\d+', 'unittest'),
    # mocha: "3 passing (1s)" / "1 failing"
    (r'^\s*\d+\s+passing\s*\(', 'mocha'),
    # RSpec: "10 examples, 2 failures"
    (r'\d+\s+examples?,\s+\d+\s+failures?', 'rspec'),
    # JUnit/Maven Surefire: "Tests run: 5, Failures: 1, Errors: 0"
    (r'Tests run:\s*\d+,\s*Failures:\s*\d+', 'junit'),
    # PHPUnit: "Tests: 12, Assertions: 30, Failures: 1"
    (r'Tests:\s*\d+,\s*Assertions:\s*\d+', 'phpunit'),
]

_FAILURE_LINE_PATTERNS: list[str] = [
    r'^FAILED\s+',
    r'^--- FAIL:',
    r'^FAIL\s+',
    r'^[✕×]\s+',
    r'^FAILED\[',
]

# Pytest summary fragments (``-q`` / classic footer).
_PYTEST_PASSED_RE = re.compile(r'(\d+)\s+passed', re.IGNORECASE)
_PYTEST_FAILED_RE = re.compile(r'(\d+)\s+failed', re.IGNORECASE)

_SUMMARY_LINE_PATTERNS: tuple[str, ...] = (
    r'=+\s*\d+\s+(passed|failed|error|skipped)',
    r'^test result:\s+(ok|FAILED)\.',
    r'^Tests:\s+\d+\s+failed,\s+\d+\s+passed,\s+\d+\s+total',
    r'^(ok|FAIL)\s+\S+\s+\d+(\.\d+)?s$',
    r'^Ran\s+\d+\s+tests?\s+in\s+\d+',
    r'^\s*\d+\s+passing\s*\(',
    r'\d+\s+examples?,\s+\d+\s+failures?',
    r'Tests run:\s*\d+,\s*Failures:\s*\d+',
    r'Tests:\s*\d+,\s*Assertions:\s*\d+',
    r'^(OK|FAILED)\s*\(',
    r'^\s*\d+\s+failing',
)


def _looks_like_test_output(output: str) -> bool:
    return any(
        re.search(pattern, output, re.IGNORECASE | re.MULTILINE)
        for pattern, _ in TEST_FRAMEWORK_PATTERNS
    )


def _is_summary_line(line: str) -> bool:
    return any(re.search(pattern, line) for pattern in _SUMMARY_LINE_PATTERNS)


def _has_failure_marker(line: str) -> bool:
    return any(
        re.search(pattern, line, re.IGNORECASE) for pattern in _FAILURE_LINE_PATTERNS
    )


def _is_actionable_failure_line(line: str) -> bool:
    if not _has_failure_marker(line):
        return False
    return bool(
        re.search(r'^FAILED\s+\S+', line) or re.search(r'^--- FAIL:', line)
    )


def _collect_summary_and_failure_lines(
    lines: list[str],
) -> tuple[list[str], list[str]]:
    summary_lines: list[str] = []
    failure_lines: list[str] = []

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if _is_summary_line(stripped):
            summary_lines.append(stripped)
        if _is_actionable_failure_line(stripped):
            failure_lines.append(stripped)

    return summary_lines, failure_lines


def _dedupe_preserving_order(lines: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for line in lines:
        if line in seen:
            continue
        deduped.append(line)
        seen.add(line)
    return deduped


def _build_test_summary_parts(
    summary_lines: list[str],
    failure_lines: list[str],
    traceback_blocks: list[str],
) -> list[str]:
    parts = ['[TEST_SUMMARY]']
    parts.extend(_dedupe_preserving_order(summary_lines))
    if failure_lines:
        parts.append('[FAILURES]')
        parts.extend(f'  {line}' for line in failure_lines[:10])
    if traceback_blocks:
        parts.append('[TRACEBACKS]')
        parts.extend(traceback_blocks)
    return parts


def extract_test_summary(output: str) -> str | None:
    """Build a ``[TEST_SUMMARY]`` block from pytest/jest/go/cargo-style stdout.

    Returns:
        A multi-line summary string, or ``None`` if no test output is detected.
    """
    lines = output.splitlines()

    if not _looks_like_test_output(output):
        return None

    summary_lines, failure_lines = _collect_summary_and_failure_lines(lines)

    # Extract Python traceback blocks (up to 5 tracebacks, first 10 lines each).
    traceback_blocks = _extract_traceback_blocks(output, max_blocks=5, max_lines=10)

    if not summary_lines and not failure_lines and not traceback_blocks:
        return None
    parts = _build_test_summary_parts(
        summary_lines,
        failure_lines,
        traceback_blocks,
    )
    return '\n'.join(parts)


def _extract_traceback_blocks(
    output: str, *, max_blocks: int = 5, max_lines: int = 10
) -> list[str]:
    """Extract Python traceback blocks from output.

    Finds ``Traceback (most recent call last):`` markers and captures
    up to ``max_lines`` of each traceback.  Returns at most ``max_blocks``
    tracebacks to avoid flooding the summary.
    """
    blocks: list[str] = []
    lines = output.splitlines()
    i = 0
    while i < len(lines) and len(blocks) < max_blocks:
        if 'Traceback (most recent call last):' in lines[i]:
            tb_lines = [lines[i]]
            i += 1
            while i < len(lines) and len(tb_lines) < max_lines:
                line = lines[i]
                tb_lines.append(line)
                # Traceback ends at the exception line (non-indented, non-empty
                # line after the File/line entries).
                if (
                    len(tb_lines) > 2
                    and line.strip()
                    and not line.startswith(' ')
                    and not line.startswith('\t')
                ):
                    break
                i += 1
            blocks.append('\n'.join(tb_lines))
        else:
            i += 1
    return blocks


def parse_pytest_pass_fail_counts(output: str) -> tuple[int, int]:
    """Parse pytest-style ``N passed`` / ``M failed`` counts from combined stdout/stderr.

    Returns:
        ``(passed, failed)`` with ``0`` for any count not present in the text.
    """
    passed = int(m.group(1)) if (m := _PYTEST_PASSED_RE.search(output)) else 0
    failed = int(m.group(1)) if (m := _PYTEST_FAILED_RE.search(output)) else 0
    return passed, failed
