"""Shared parsing of test-runner stdout for truncation and review.

Patterns are duplicated in a single module so ``truncate_cmd_output`` and
``SuitePassCritic`` stay aligned and regressions are caught by one test suite.
"""

from __future__ import annotations

import re

# (pattern, framework label) — used for "does this blob look like test output?"
TEST_FRAMEWORK_PATTERNS: list[tuple[str, str]] = [
    (r"=+\s*\d+\s+(passed|failed|error|skipped)", "pytest"),
    (r"^Tests:\s+\d+\s+failed,\s+\d+\s+passed,\s+\d+\s+total", "jest"),
    (r"^test result:\s+(ok|FAILED)\.", "cargo"),
    (r"^(ok|FAIL)\s+\S+\s+\d+(\.\d+)?s$", "go"),
]

_FAILURE_LINE_PATTERNS: list[str] = [
    r"^FAILED\s+",
    r"^--- FAIL:",
    r"^FAIL\s+",
    r"^[✕×]\s+",
    r"^FAILED\[",
]

# Pytest summary fragments (``-q`` / classic footer).
_PYTEST_PASSED_RE = re.compile(r"(\d+)\s+passed", re.IGNORECASE)
_PYTEST_FAILED_RE = re.compile(r"(\d+)\s+failed", re.IGNORECASE)


def extract_test_summary(output: str) -> str | None:
    """Build a ``[TEST_SUMMARY]`` block from pytest/jest/go/cargo-style stdout.

    Returns:
        A multi-line summary string, or ``None`` if no test output is detected.
    """
    lines = output.splitlines()

    # MULTILINE: patterns use ``^`` for line starts; search runs on the full blob.
    is_test_output = any(
        re.search(pat, output, re.IGNORECASE | re.MULTILINE)
        for pat, _ in TEST_FRAMEWORK_PATTERNS
    )
    if not is_test_output:
        return None

    summary_lines: list[str] = []
    failure_lines: list[str] = []

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        if re.search(r"=+\s*\d+\s+(passed|failed|error|skipped)", stripped):
            summary_lines.append(stripped)
        elif re.search(r"^test result:\s+(ok|FAILED)\.", stripped):
            summary_lines.append(stripped)
        elif re.search(
            r"^Tests:\s+\d+\s+failed,\s+\d+\s+passed,\s+\d+\s+total", stripped
        ):
            summary_lines.append(stripped)
        elif re.search(r"^(ok|FAIL)\s+\S+\s+\d+(\.\d+)?s$", stripped):
            summary_lines.append(stripped)

        if any(re.search(pat, stripped, re.IGNORECASE) for pat in _FAILURE_LINE_PATTERNS):
            if re.search(r"^FAILED\s+\S+", stripped) or re.search(
                r"^--- FAIL:", stripped
            ):
                failure_lines.append(stripped)

    if not summary_lines and not failure_lines:
        return None

    parts = ["[TEST_SUMMARY]"]
    if summary_lines:
        seen: set[str] = set()
        for sline in summary_lines:
            if sline not in seen:
                parts.append(sline)
                seen.add(sline)
    if failure_lines:
        parts.append("[FAILURES]")
        for fl in failure_lines[:10]:
            parts.append(f"  {fl}")
    return "\n".join(parts)


def parse_pytest_pass_fail_counts(output: str) -> tuple[int, int]:
    """Parse pytest-style ``N passed`` / ``M failed`` counts from combined stdout/stderr.

    Returns:
        ``(passed, failed)`` with ``0`` for any count not present in the text.
    """
    passed = int(m.group(1)) if (m := _PYTEST_PASSED_RE.search(output)) else 0
    failed = int(m.group(1)) if (m := _PYTEST_FAILED_RE.search(output)) else 0
    return passed, failed
