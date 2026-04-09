"""Tests for backend.engine.tools.smart_errors — SmartErrorHandler."""

# pylint: disable=protected-access
from __future__ import annotations

import pytest

from backend.engine.tools.smart_errors import (
    ErrorSuggestion,
    SmartErrorHandler,
)

# ── ErrorSuggestion dataclass ──────────────────────────────────────────


class TestErrorSuggestion:
    def test_basic(self):
        s = ErrorSuggestion(message='fail', suggestions=['a', 'b'], confidence=0.8)
        assert s.message == 'fail'
        assert s.suggestions == ['a', 'b']
        assert s.confidence == 0.8
        assert s.auto_fixable is False
        assert s.fix_code is None

    def test_auto_fixable(self):
        s = ErrorSuggestion(
            message='typo',
            suggestions=['function'],
            confidence=0.95,
            auto_fixable=True,
            fix_code='function',
        )
        assert s.auto_fixable is True
        assert s.fix_code == 'function'


# ── _check_common_typo ─────────────────────────────────────────────────


class TestCheckCommonTypo:
    @pytest.mark.parametrize(
        'typo,correction',
        [
            ('functino', 'function'),
            ('fucntion', 'function'),
            ('calss', 'class'),
            ('improt', 'import'),
            ('retrun', 'return'),
        ],
    )
    def test_known_typos(self, typo, correction):
        result = SmartErrorHandler._check_common_typo(typo)
        assert result is not None
        assert result.confidence == 0.95
        assert correction in result.suggestions
        assert result.auto_fixable is True
        assert result.fix_code == correction

    def test_case_insensitive(self):
        result = SmartErrorHandler._check_common_typo('FUNCTINO')
        assert result is not None
        assert 'function' in result.suggestions

    def test_not_a_typo(self):
        assert SmartErrorHandler._check_common_typo('valid_name') is None


# ── _create_fuzzy_match_suggestion ─────────────────────────────────────


class TestCreateFuzzyMatchSuggestion:
    def test_high_similarity(self):
        result = SmartErrorHandler._create_fuzzy_match_suggestion('proces', ['process'])
        assert result.auto_fixable is True
        assert result.confidence > 0.7

    def test_medium_similarity(self):
        result = SmartErrorHandler._create_fuzzy_match_suggestion(
            'prcs', ['process', 'produce']
        )
        assert (
            'Similar symbols' in result.message or 'Possible matches' in result.message
        )

    def test_low_similarity(self):
        result = SmartErrorHandler._create_fuzzy_match_suggestion(
            'xyz', ['abcdef', 'ghijkl']
        )
        assert result.auto_fixable is False


# ── symbol_not_found ───────────────────────────────────────────────────


class TestSymbolNotFound:
    def test_typo_detected(self):
        result = SmartErrorHandler.symbol_not_found('functino', ['function', 'main'])
        assert 'function' in result.suggestions
        assert result.confidence == 0.95

    def test_fuzzy_match(self):
        result = SmartErrorHandler.symbol_not_found('my_func', ['my_function', 'other'])
        assert result.suggestions

    def test_no_match_lists_available(self):
        result = SmartErrorHandler.symbol_not_found('zzz', ['alpha', 'beta'])
        assert 'Available symbols' in result.message or 'not found' in result.message

    def test_empty_available(self):
        result = SmartErrorHandler.symbol_not_found('foo', [])
        assert 'no symbols are available' in result.message
        assert result.confidence == 0.0


# ── _group_symbols_by_type ─────────────────────────────────────────────


class TestGroupSymbolsByType:
    def test_separation(self):
        funcs, classes = SmartErrorHandler._group_symbols_by_type(
            ['MyClass', 'my_func', 'AnotherClass', 'helper']
        )
        assert set(funcs) == {'my_func', 'helper'}
        assert set(classes) == {'MyClass', 'AnotherClass'}

    def test_all_functions(self):
        funcs, classes = SmartErrorHandler._group_symbols_by_type(['a', 'b', 'c'])
        assert len(funcs) == 3
        assert not classes


# ── _build_symbol_context ──────────────────────────────────────────────


class TestBuildSymbolContext:
    def test_both(self):
        result = SmartErrorHandler._build_symbol_context(['A', 'B'], ['f1'])
        assert '2 classes' in result
        assert '1 function' in result

    def test_empty(self):
        assert SmartErrorHandler._build_symbol_context([], []) == ''
