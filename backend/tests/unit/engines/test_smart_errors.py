"""Tests for backend.engines.orchestrator.tools.smart_errors — SmartErrorHandler."""

# pylint: disable=protected-access
from __future__ import annotations

import pytest

from backend.engines.orchestrator.tools.smart_errors import (
    ErrorSuggestion,
    SmartErrorHandler,
)


# ── ErrorSuggestion dataclass ──────────────────────────────────────────


class TestErrorSuggestion:
    def test_basic(self):
        s = ErrorSuggestion(message="fail", suggestions=["a", "b"], confidence=0.8)
        assert s.message == "fail"
        assert s.suggestions == ["a", "b"]
        assert s.confidence == 0.8
        assert s.auto_fixable is False
        assert s.fix_code is None

    def test_auto_fixable(self):
        s = ErrorSuggestion(
            message="typo",
            suggestions=["function"],
            confidence=0.95,
            auto_fixable=True,
            fix_code="function",
        )
        assert s.auto_fixable is True
        assert s.fix_code == "function"


# ── _check_common_typo ─────────────────────────────────────────────────


class TestCheckCommonTypo:
    @pytest.mark.parametrize(
        "typo,correction",
        [
            ("functino", "function"),
            ("fucntion", "function"),
            ("calss", "class"),
            ("improt", "import"),
            ("retrun", "return"),
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
        result = SmartErrorHandler._check_common_typo("FUNCTINO")
        assert result is not None
        assert "function" in result.suggestions

    def test_not_a_typo(self):
        assert SmartErrorHandler._check_common_typo("valid_name") is None


# ── _create_fuzzy_match_suggestion ─────────────────────────────────────


class TestCreateFuzzyMatchSuggestion:
    def test_high_similarity(self):
        result = SmartErrorHandler._create_fuzzy_match_suggestion("proces", ["process"])
        assert result.auto_fixable is True
        assert result.confidence > 0.7

    def test_medium_similarity(self):
        result = SmartErrorHandler._create_fuzzy_match_suggestion(
            "prcs", ["process", "produce"]
        )
        assert (
            "Similar symbols" in result.message or "Possible matches" in result.message
        )

    def test_low_similarity(self):
        result = SmartErrorHandler._create_fuzzy_match_suggestion(
            "xyz", ["abcdef", "ghijkl"]
        )
        assert result.auto_fixable is False


# ── symbol_not_found ───────────────────────────────────────────────────


class TestSymbolNotFound:
    def test_typo_detected(self):
        result = SmartErrorHandler.symbol_not_found("functino", ["function", "main"])
        assert "function" in result.suggestions
        assert result.confidence == 0.95

    def test_fuzzy_match(self):
        result = SmartErrorHandler.symbol_not_found("my_func", ["my_function", "other"])
        assert result.suggestions

    def test_no_match_lists_available(self):
        result = SmartErrorHandler.symbol_not_found("zzz", ["alpha", "beta"])
        assert "Available symbols" in result.message or "not found" in result.message

    def test_empty_available(self):
        result = SmartErrorHandler.symbol_not_found("foo", [])
        assert "no symbols are available" in result.message
        assert result.confidence == 0.0


# ── _group_symbols_by_type ─────────────────────────────────────────────


class TestGroupSymbolsByType:
    def test_separation(self):
        funcs, classes = SmartErrorHandler._group_symbols_by_type(
            ["MyClass", "my_func", "AnotherClass", "helper"]
        )
        assert set(funcs) == {"my_func", "helper"}
        assert set(classes) == {"MyClass", "AnotherClass"}

    def test_all_functions(self):
        funcs, classes = SmartErrorHandler._group_symbols_by_type(["a", "b", "c"])
        assert len(funcs) == 3
        assert not classes


# ── _build_symbol_context ──────────────────────────────────────────────


class TestBuildSymbolContext:
    def test_both(self):
        result = SmartErrorHandler._build_symbol_context(["A", "B"], ["f1"])
        assert "2 classes" in result
        assert "1 functions" in result

    def test_empty(self):
        assert SmartErrorHandler._build_symbol_context([], []) == ""


# ── syntax_error ───────────────────────────────────────────────────────


class TestSyntaxError:
    def test_indent_error(self):
        result = SmartErrorHandler.syntax_error("unexpected indent at line 5")
        assert any(
            "indentation" in s.lower() or "spacing" in s.lower()
            for s in result.suggestions
        )
        assert result.confidence >= 0.8

    def test_unterminated_string(self):
        result = SmartErrorHandler.syntax_error("unterminated string literal")
        assert any("unclosed string" in s for s in result.suggestions)
        assert result.confidence == 0.9

    def test_invalid_syntax_with_context(self):
        result = SmartErrorHandler.syntax_error(
            "invalid syntax", line_number=10, code_context="if True"
        )
        assert "line 10" in result.message
        assert "Context" in result.message

    def test_eof_error(self):
        result = SmartErrorHandler.syntax_error("unexpected EOF while parsing")
        assert any(
            "unclosed" in s.lower() or "brackets" in s.lower()
            for s in result.suggestions
        )

    def test_undefined_error(self):
        result = SmartErrorHandler.syntax_error("name 'foo' is not defined")
        assert any(
            "defined" in s.lower() or "typos" in s.lower() for s in result.suggestions
        )

    def test_generic_error(self):
        result = SmartErrorHandler.syntax_error("some random error")
        # Should still return a valid ErrorSuggestion
        assert isinstance(result, ErrorSuggestion)


# ── _analyze helpers ───────────────────────────────────────────────────


class TestAnalyzeHelpers:
    def test_analyze_indent_error_match(self):
        suggestions, conf = SmartErrorHandler._analyze_indent_error("unexpected indent")
        assert suggestions
        assert conf == 0.8

    def test_analyze_indent_error_no_match(self):
        suggestions, conf = SmartErrorHandler._analyze_indent_error("other error")
        assert not suggestions
        assert conf == 0.5

    def test_analyze_string_error_match(self):
        suggestions, conf = SmartErrorHandler._analyze_string_error(
            "unterminated string"
        )
        assert suggestions
        assert conf == 0.9

    def test_analyze_string_error_no_match(self):
        suggestions, _ = SmartErrorHandler._analyze_string_error("other error")
        assert not suggestions

    def test_analyze_eof_error_match(self):
        suggestions, conf = SmartErrorHandler._analyze_eof_error("unexpected eof")
        assert suggestions
        assert conf == 0.85

    def test_analyze_undefined_error_match(self):
        suggestions, conf = SmartErrorHandler._analyze_undefined_error(
            "name not defined"
        )
        assert suggestions
        assert conf == 0.75


# ── _check helpers ─────────────────────────────────────────────────────


class TestCheckHelpers:
    def test_check_missing_colon_present(self):
        assert SmartErrorHandler._check_missing_colon("if True:") is not None

    def test_check_missing_colon_absent(self):
        assert SmartErrorHandler._check_missing_colon("x = 1") is None

    def test_check_unmatched_parentheses(self):
        assert SmartErrorHandler._check_unmatched_parentheses("print(x") is not None

    def test_check_matched_parentheses(self):
        assert SmartErrorHandler._check_unmatched_parentheses("print(x)") is None

    def test_check_unmatched_brackets(self):
        assert SmartErrorHandler._check_unmatched_brackets("a[0") is not None

    def test_check_matched_brackets(self):
        assert SmartErrorHandler._check_unmatched_brackets("a[0]") is None


# ── file_not_found ─────────────────────────────────────────────────────


class TestFileNotFound:
    def test_no_similar(self):
        result = SmartErrorHandler.file_not_found("missing.py")
        assert "File not found" in result.message
        assert result.confidence == 0.0

    def test_with_similar_files(self):
        result = SmartErrorHandler.file_not_found(
            "app.py", ["app.py.bak", "main.py", "apps.py"]
        )
        assert result.suggestions

    def test_close_match_auto_fixable(self):
        result = SmartErrorHandler.file_not_found(
            "src/main.py", ["src/main.py", "src/main.js"]
        )
        # Exact match should be very similar
        if result.confidence > 0.85:
            assert result.auto_fixable is True

    def test_no_close_matches(self):
        result = SmartErrorHandler.file_not_found("zzz.py", ["alpha.js", "beta.rs"])
        assert "No similar files" in result.message


# ── whitespace_mismatch ────────────────────────────────────────────────


class TestWhitespaceMismatch:
    def test_tabs_vs_spaces(self):
        result = SmartErrorHandler.whitespace_mismatch(
            expected_indent="    ", actual_indent="\t", line_number=5
        )
        assert "spaces" in result.message
        assert "tabs" in result.message
        assert result.confidence == 1.0
        assert result.auto_fixable is True

    def test_different_space_count(self):
        result = SmartErrorHandler.whitespace_mismatch(
            expected_indent="    ", actual_indent="  ", line_number=10
        )
        assert "4" in result.message
        assert "2" in result.message


# ── suggest_similar ────────────────────────────────────────────────────


class TestSuggestSimilar:
    def test_finds_matches(self):
        matches = SmartErrorHandler.suggest_similar("tset", ["test", "best", "rest"])
        assert "test" in matches

    def test_high_threshold_filters(self):
        matches = SmartErrorHandler.suggest_similar(
            "abc", ["xyz", "lmn"], threshold=0.9
        )
        assert matches == []

    def test_empty_candidates(self):
        assert SmartErrorHandler.suggest_similar("foo", []) == []


# ── format_edit_conflict ───────────────────────────────────────────────


class TestFormatEditConflict:
    def test_basic(self):
        result = SmartErrorHandler.format_edit_conflict(
            "src/main.py", "renamed variable", "deleted function"
        )
        assert "src/main.py" in result.message
        assert "renamed variable" in result.message
        assert "Conflicts with" in result.message
        assert result.confidence == 1.0


# ── validate_edit_result ───────────────────────────────────────────────


class TestValidateEditResult:
    def test_no_change(self):
        result = SmartErrorHandler.validate_edit_result("code", "code")
        assert result is not None
        assert "did not change" in result.message

    def test_normal_change(self):
        result = SmartErrorHandler.validate_edit_result("old", "new")
        assert result is None

    def test_dramatic_shrink(self):
        original = "\n".join(f"line {i}" for i in range(200))
        new = "single line"
        result = SmartErrorHandler.validate_edit_result(original, new)
        assert result is not None
        assert "shrank dramatically" in result.message

    def test_small_file_shrink_ok(self):
        # Small files (<= 100 lines) don't trigger shrink warning
        original = "\n".join(f"line {i}" for i in range(50))
        new = "single line"
        result = SmartErrorHandler.validate_edit_result(original, new)
        assert result is None
