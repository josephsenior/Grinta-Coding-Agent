"""Golden-style tests for test runner stdout parsing (shared module)."""

from __future__ import annotations

import pytest

from backend.execution.file_operations import truncate_cmd_output
from backend.execution.utils.test_output_summary import (
    extract_test_summary,
    parse_pytest_pass_fail_counts,
)


@pytest.mark.parametrize(
    ('name', 'raw', 'expect_substrings'),
    [
        (
            'pytest_footer',
            'setup\n================ 5 passed in 0.12s ================\n',
            ['[TEST_SUMMARY]', '5 passed'],
        ),
        (
            'pytest_with_failures',
            'FAILED tests/test_x.py::test_a - assert 0\n'
            '================ 1 failed, 4 passed in 1.0s ================\n',
            ['[TEST_SUMMARY]', '[FAILURES]', 'FAILED '],
        ),
        (
            'cargo_ok',
            '\nrunning 3 tests\n...\ntest result: ok. 3 passed; 0 failed\n',
            ['[TEST_SUMMARY]', 'test result: ok.'],
        ),
        (
            'go_package_ok',
            'ok  \tgithub.com/acme/pkg\t0.045s\n',
            ['[TEST_SUMMARY]', 'ok', 'github.com/acme/pkg'],
        ),
        (
            'jest_summary',
            'Ran all test suites.\nTests:       2 failed, 2 passed, 4 total\n',
            ['[TEST_SUMMARY]', 'Tests:', 'failed', 'passed'],
        ),
    ],
)
def test_extract_test_summary_detects_frameworks(
    name: str, raw: str, expect_substrings: list[str]
) -> None:
    summary = extract_test_summary(raw)
    assert summary is not None, name
    for frag in expect_substrings:
        assert frag in summary, (name, frag, summary)


def test_extract_test_summary_none_for_non_test_output() -> None:
    assert extract_test_summary('System error while connecting to host\n') is None


def test_truncate_cmd_output_prepends_test_summary() -> None:
    raw = 'noise\n================ 3 passed in 0.1s ================\n'
    out = truncate_cmd_output(raw, max_chars=10_000)
    assert out.startswith('[TEST_SUMMARY]')


@pytest.mark.parametrize(
    ('output', 'passed', 'failed'),
    [
        ('= 5 passed in 0.1s =', 5, 0),
        ('3 failed, 10 passed in 1s', 10, 3),
        ('no summary here', 0, 0),
        ('ERROR: 99 is not 100\n2 failed, 5 passed', 5, 2),
    ],
)
def test_parse_pytest_pass_fail_counts(output: str, passed: int, failed: int) -> None:
    assert parse_pytest_pass_fail_counts(output) == (passed, failed)
