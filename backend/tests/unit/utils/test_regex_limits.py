"""Tests for user regex guardrails."""

from __future__ import annotations

from backend.utils.regex_limits import (
    MAX_USER_REGEX_PATTERN_CHARS,
    try_compile_user_regex,
)


def test_oversized_pattern_rejected() -> None:
    pat = 'a' * (MAX_USER_REGEX_PATTERN_CHARS + 1)
    r, err = try_compile_user_regex(pat)
    assert r is None
    assert err is not None


def test_valid_pattern_compiles() -> None:
    r, err = try_compile_user_regex(r'foo\d+')
    assert r is not None and err is None
    assert r.search('foo42')
