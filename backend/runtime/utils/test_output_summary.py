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
    # unittest: "Ran 42 tests in 1.234s"
    (r"^Ran\s+\d+\s+tests?\s+in\s+\d+", "unittest"),
    # mocha: "3 passing (1s)" / "1 failing"
    (r"^\s*\d+\s+passing\s*\(", "mocha"),
    # RSpec: "10 examples, 2 failures"
    (r"\d+\s+examples?,\s+\d+\s+failures?", "rspec"),
    # JUnit/Maven Surefire: "Tests run: 5, Failures: 1, Errors: 0"
    (r"Tests run:\s*\d+,\s*Failures:\s*\d+", "junit"),
    # PHPUnit: "Tests: 12, Assertions: 30, Failures: 1"
    (r"Tests:\s*\d+,\s*Assertions:\s*\d+", "phpunit"),
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

        # --- Existing framework summary detection ---
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
        # --- New framework summary detection ---
        elif re.search(r"^Ran\s+\d+\s+tests?\s+in\s+\d+", stripped):
            summary_lines.append(stripped)
        elif re.search(r"^\s*\d+\s+passing\s*\(", stripped):
            summary_lines.append(stripped)
        elif re.search(r"\d+\s+examples?,\s+\d+\s+failures?", stripped):
            summary_lines.append(stripped)
        elif re.search(r"Tests run:\s*\d+,\s*Failures:\s*\d+", stripped):
            summary_lines.append(stripped)
        elif re.search(r"Tests:\s*\d+,\s*Assertions:\s*\d+", stripped):
            summary_lines.append(stripped)
        # --- unittest "FAILED (failures=N)" / "OK" ---
        elif re.search(r"^(OK|FAILED)\s*\(", stripped):
            summary_lines.append(stripped)
        # --- mocha "N failing" ---
        elif re.search(r"^\s*\d+\s+failing", stripped):
            summary_lines.append(stripped)

        if any(re.search(pat, stripped, re.IGNORECASE) for pat in _FAILURE_LINE_PATTERNS):
            if re.search(r"^FAILED\s+\S+", stripped) or re.search(
                r"^--- FAIL:", stripped
            ):
                failure_lines.append(stripped)

    # Extract Python traceback blocks (up to 5 tracebacks, first 10 lines each).
    traceback_blocks = _extract_traceback_blocks(output, max_blocks=5, max_lines=10)

    if not summary_lines and not failure_lines and not traceback_blocks:
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
    if traceback_blocks:
        parts.append("[TRACEBACKS]")
        for tb in traceback_blocks:
            parts.append(tb)
    return "\n".join(parts)


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
        if "Traceback (most recent call last):" in lines[i]:
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
                    and not line.startswith(" ")
                    and not line.startswith("\t")
                ):
                    break
                i += 1
            blocks.append("\n".join(tb_lines))
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
