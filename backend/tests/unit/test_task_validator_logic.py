"""Tests for backend.validation.task_validator — validation dataclasses and pure logic."""

from __future__ import annotations

import pytest

from backend.validation.task_validator import (
    CompositeValidator,
    DiffValidator,
    FileExistsValidator,
    Task,
    TaskValidator,
    ValidationResult,
)


# ── Task dataclass ───────────────────────────────────────────────────


class TestTask:
    def test_defaults(self):
        t = Task(description="Fix bug")
        assert t.description == "Fix bug"
        assert t.requirements == []
        assert t.acceptance_criteria == []

    def test_custom(self):
        t = Task(
            description="Add feature",
            requirements=["Write tests"],
            acceptance_criteria=["All tests pass"],
        )
        assert len(t.requirements) == 1
        assert len(t.acceptance_criteria) == 1


# ── ValidationResult dataclass ───────────────────────────────────────


class TestValidationResult:
    def test_defaults(self):
        r = ValidationResult(passed=True, reason="OK")
        assert r.passed is True
        assert r.confidence == 1.0
        assert r.missing_items == []
        assert r.suggestions == []

    def test_custom(self):
        r = ValidationResult(
            passed=False,
            reason="Tests failed",
            confidence=0.8,
            missing_items=["Fix test"],
            suggestions=["Run tests"],
        )
        assert r.passed is False
        assert r.confidence == 0.8
        assert len(r.missing_items) == 1


# ── TaskValidator ABC ────────────────────────────────────────────────


class TestTaskValidatorABC:
    def test_cannot_instantiate(self):
        with pytest.raises(TypeError):
            TaskValidator()  # type: ignore


# ── DiffValidator pure-logic methods ─────────────────────────────────


class TestDiffValidatorLogic:
    @pytest.fixture()
    def validator(self):
        return DiffValidator()

    def test_is_diff_metadata_git(self, validator):
        assert validator._is_diff_metadata("diff --git a/file b/file") is True

    def test_is_diff_metadata_index(self, validator):
        assert validator._is_diff_metadata("index 1234567..abcdef0 100644") is True

    def test_is_diff_metadata_plus(self, validator):
        assert validator._is_diff_metadata("+++ b/file.py") is True

    def test_is_diff_metadata_minus(self, validator):
        assert validator._is_diff_metadata("--- a/file.py") is True

    def test_is_diff_metadata_regular_line(self, validator):
        assert validator._is_diff_metadata("+def foo():") is False

    def test_is_comment_hash(self, validator):
        assert validator._is_comment_line("# This is a comment") is True

    def test_is_comment_slashes(self, validator):
        assert validator._is_comment_line("// Also a comment") is True

    def test_is_not_comment(self, validator):
        assert validator._is_comment_line("def foo():") is False

    def test_is_meaningful_added_code(self, validator):
        assert validator._is_meaningful_change_line("+def foo():") is True

    def test_is_meaningful_removed_code(self, validator):
        assert validator._is_meaningful_change_line("-old_function()") is True

    def test_not_meaningful_context_line(self, validator):
        assert validator._is_meaningful_change_line(" context line") is False

    def test_not_meaningful_empty_add(self, validator):
        assert validator._is_meaningful_change_line("+") is False

    def test_not_meaningful_comment(self, validator):
        assert validator._is_meaningful_change_line("+# comment") is False

    def test_not_meaningful_metadata(self, validator):
        assert validator._is_meaningful_change_line("diff --git a/f b/f") is False

    def test_count_meaningful_changes(self, validator):
        diff = """diff --git a/file.py b/file.py
--- a/file.py
+++ b/file.py
 context
+def new_func():
+    return 42
-old_func()
+# this is a comment
+ 
"""
        count = validator._count_meaningful_changes(diff)
        # +def new_func(): (meaningful), +    return 42 (meaningful), -old_func() (meaningful)
        # +# this is a comment (NOT meaningful — is a comment)
        # +  (NOT meaningful — whitespace only)
        assert count == 3

    def test_count_meaningful_empty_diff(self, validator):
        assert validator._count_meaningful_changes("") == 0


# ── FileExistsValidator pure-logic ───────────────────────────────────


class TestFileExistsValidatorLogic:
    def test_extract_create_file(self):
        v = FileExistsValidator()
        files = v._extract_expected_files('Create a file "output.txt" with the results')
        assert "output.txt" in files

    def test_extract_save_to(self):
        v = FileExistsValidator()
        files = v._extract_expected_files("Save to results.csv")
        assert "results.csv" in files

    def test_extract_output_to(self):
        v = FileExistsValidator()
        files = v._extract_expected_files("Output to report.html")
        assert "report.html" in files

    def test_extract_no_files(self):
        v = FileExistsValidator()
        files = v._extract_expected_files("Fix the bug in the login page")
        assert files == []

    def test_extract_deduplicates(self):
        v = FileExistsValidator()
        files = v._extract_expected_files(
            'Create file "data.json" and save to data.json'
        )
        assert files.count("data.json") == 1

    def test_default_expected_files(self):
        v = FileExistsValidator()
        assert v.expected_files == []

    def test_custom_expected_files(self):
        v = FileExistsValidator(expected_files=["a.py", "b.py"])
        assert v.expected_files == ["a.py", "b.py"]


# ── CompositeValidator pure-logic ────────────────────────────────────


class TestCompositeValidatorLogic:
    def test_calculate_vote_metrics_all_passed(self):
        cv = CompositeValidator(validators=[])
        results = [
            ValidationResult(passed=True, reason="ok", confidence=0.9),
            ValidationResult(passed=True, reason="ok", confidence=0.7),
        ]
        passed, avg_conf = cv._calculate_vote_metrics(results)
        assert passed == 2
        assert abs(avg_conf - 0.8) < 0.001

    def test_calculate_vote_metrics_mixed(self):
        cv = CompositeValidator(validators=[])
        results = [
            ValidationResult(passed=True, reason="ok", confidence=1.0),
            ValidationResult(passed=False, reason="fail", confidence=0.5),
        ]
        passed, avg_conf = cv._calculate_vote_metrics(results)
        assert passed == 1
        assert abs(avg_conf - 0.75) < 0.001

    def test_vote_passes_majority_and_confidence(self):
        cv = CompositeValidator(validators=[], min_confidence=0.7)
        assert cv._vote_passes(2, 3, 0.8) is True

    def test_vote_fails_minority(self):
        cv = CompositeValidator(validators=[], min_confidence=0.7)
        assert cv._vote_passes(1, 3, 0.8) is False

    def test_vote_fails_low_confidence(self):
        cv = CompositeValidator(validators=[], min_confidence=0.7)
        assert cv._vote_passes(2, 3, 0.5) is False

    def test_validate_all_must_pass_success(self):
        cv = CompositeValidator(validators=[], require_all_pass=True)
        results = [
            ValidationResult(passed=True, reason="a", confidence=0.9),
            ValidationResult(passed=True, reason="b", confidence=0.8),
        ]
        result = cv._validate_all_must_pass(results)
        assert result.passed is True
        assert result.confidence == 0.8  # min of confidences

    def test_validate_all_must_pass_failure(self):
        cv = CompositeValidator(validators=[], require_all_pass=True)
        results = [
            ValidationResult(passed=True, reason="a", confidence=0.9),
            ValidationResult(
                passed=False,
                reason="fail",
                confidence=0.7,
                missing_items=["item"],
            ),
        ]
        result = cv._validate_all_must_pass(results)
        assert result.passed is False
        assert "1 validator(s) failed" in result.reason
        assert "item" in result.missing_items

    def test_validate_weighted_failure(self):
        cv = CompositeValidator(validators=[], min_confidence=0.7)
        results = [
            ValidationResult(
                passed=False,
                reason="fail1",
                confidence=0.3,
                missing_items=["fix"],
            ),
            ValidationResult(passed=False, reason="fail2", confidence=0.4),
        ]
        result = cv._validate_weighted_vote(results)
        assert result.passed is False
        assert "fix" in result.missing_items
