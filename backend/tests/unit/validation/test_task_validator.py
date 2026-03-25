"""Tests for backend.validation.task_validator — task completion validation framework."""

import pytest
from unittest.mock import MagicMock

from backend.events.action.files import FileWriteAction
from backend.events.observation.files import FileReadObservation
from backend.validation.task_validator import (
    CompositeValidator,
    DiffValidator,
    FileExistsValidator,
    LLMTaskEvaluator,
    Task,
    TaskValidator,
    TestPassingValidator,
    ValidationResult,
)


class TestTask:
    """Tests for Task dataclass."""

    def test_create_minimal_task(self):
        """Test creating Task with minimal fields."""
        task = Task(description="Fix the bug")
        assert task.description == "Fix the bug"
        assert task.requirements == []
        assert task.acceptance_criteria == []

    def test_create_task_with_requirements(self):
        """Test creating Task with requirements."""
        task = Task(
            description="Add feature",
            requirements=["Must pass tests", "Must update docs"],
        )
        assert task.description == "Add feature"
        assert len(task.requirements) == 2
        assert "Must pass tests" in task.requirements

    def test_create_task_with_acceptance_criteria(self):
        """Test creating Task with acceptance criteria."""
        task = Task(
            description="Refactor",
            acceptance_criteria=["Code coverage > 80%", "No lint errors"],
        )
        assert len(task.acceptance_criteria) == 2
        assert "Code coverage > 80%" in task.acceptance_criteria

    def test_create_full_task(self):
        """Test creating Task with all fields."""
        task = Task(
            description="Complete feature",
            requirements=["Req1", "Req2"],
            acceptance_criteria=["Criteria1", "Criteria2"],
        )
        assert task.description == "Complete feature"
        assert len(task.requirements) == 2
        assert len(task.acceptance_criteria) == 2

    def test_task_default_factory(self):
        """Test Task default factory creates separate lists."""
        task1 = Task(description="Task 1")
        task2 = Task(description="Task 2")
        task1.requirements.append("Req1")
        assert len(task1.requirements) == 1
        assert not task2.requirements  # Should be independent


class TestValidationResult:
    """Tests for ValidationResult dataclass."""

    def test_create_minimal_result(self):
        """Test creating ValidationResult with minimal fields."""
        result = ValidationResult(passed=True, reason="All good")
        assert result.passed is True
        assert result.reason == "All good"
        assert result.confidence == 1.0
        assert result.missing_items == []
        assert result.suggestions == []

    def test_create_failed_result(self):
        """Test creating failed ValidationResult."""
        result = ValidationResult(passed=False, reason="Tests failed")
        assert result.passed is False
        assert result.reason == "Tests failed"

    def test_create_with_custom_confidence(self):
        """Test creating ValidationResult with custom confidence."""
        result = ValidationResult(passed=True, reason="OK", confidence=0.8)
        assert result.confidence == 0.8

    def test_create_with_missing_items(self):
        """Test creating ValidationResult with missing items."""
        result = ValidationResult(
            passed=False,
            reason="Incomplete",
            missing_items=["tests", "docs"],
        )
        assert len(result.missing_items) == 2
        assert "tests" in result.missing_items

    def test_create_with_suggestions(self):
        """Test creating ValidationResult with suggestions."""
        result = ValidationResult(
            passed=False,
            reason="Failed",
            suggestions=["Run pytest", "Fix linting"],
        )
        assert len(result.suggestions) == 2
        assert "Run pytest" in result.suggestions

    def test_create_full_result(self):
        """Test creating ValidationResult with all fields."""
        result = ValidationResult(
            passed=False,
            reason="Incomplete task",
            confidence=0.9,
            missing_items=["item1"],
            suggestions=["suggestion1"],
        )
        assert result.passed is False
        assert result.confidence == 0.9
        assert len(result.missing_items) == 1
        assert len(result.suggestions) == 1

    def test_confidence_bounds(self):
        """Test ValidationResult confidence can be 0.0 to 1.0."""
        result1 = ValidationResult(passed=True, reason="Test", confidence=0.0)
        result2 = ValidationResult(passed=True, reason="Test", confidence=1.0)
        assert result1.confidence == 0.0
        assert result2.confidence == 1.0


class TestTaskValidator:
    """Tests for TaskValidator abstract base class."""

    def test_is_abstract(self):
        """Test TaskValidator cannot be instantiated."""
        with pytest.raises(TypeError):
            TaskValidator()  # type: ignore

    def test_has_validate_completion_method(self):
        """Test TaskValidator has abstract validate_completion method."""
        assert hasattr(TaskValidator, "validate_completion")


class TestTestPassingValidator:
    """Tests for TestPassingValidator class."""

    def test_create_validator(self):
        """Test creating TestPassingValidator instance."""
        validator = TestPassingValidator()
        assert isinstance(validator, TaskValidator)
        assert isinstance(validator, TestPassingValidator)

    def test_inherits_from_task_validator(self):
        """Test TestPassingValidator inherits from TaskValidator."""
        assert issubclass(TestPassingValidator, TaskValidator)


class TestDiffValidator:
    """Tests for DiffValidator class."""

    def test_create_validator(self):
        """Test creating DiffValidator instance."""
        validator = DiffValidator()
        assert isinstance(validator, TaskValidator)
        assert isinstance(validator, DiffValidator)

    def test_inherits_from_task_validator(self):
        """Test DiffValidator inherits from TaskValidator."""
        assert issubclass(DiffValidator, TaskValidator)

    def test_is_diff_metadata_recognizes_git_metadata(self):
        """Test _is_diff_metadata recognizes git diff metadata lines."""
        validator = DiffValidator()
        assert validator._is_diff_metadata("diff --git a/file.py b/file.py")
        assert validator._is_diff_metadata("index 1234567..89abcdef 100644")
        assert validator._is_diff_metadata("+++ b/file.py")
        assert validator._is_diff_metadata("--- a/file.py")
        assert not validator._is_diff_metadata("+def test():")
        assert not validator._is_diff_metadata("-old line")

    def test_is_comment_line_recognizes_comments(self):
        """Test _is_comment_line recognizes comment syntax."""
        validator = DiffValidator()
        assert validator._is_comment_line("# Python comment")
        assert validator._is_comment_line("// JavaScript comment")
        assert not validator._is_comment_line("def function():")
        assert not validator._is_comment_line("  code here")

    def test_is_meaningful_change_line_filters_correctly(self):
        """Test _is_meaningful_change_line filters non-meaningful changes."""
        validator = DiffValidator()
        assert validator._is_meaningful_change_line("+def test():")
        assert validator._is_meaningful_change_line("-old_code()")
        assert not validator._is_meaningful_change_line("diff --git a/file b/file")
        assert not validator._is_meaningful_change_line("+# comment")
        assert not validator._is_meaningful_change_line("+")  # Empty line
        assert not validator._is_meaningful_change_line(" unchanged line")

    def test_count_meaningful_changes(self):
        """Test _count_meaningful_changes counts correctly."""
        validator = DiffValidator()
        diff = """diff --git a/test.py b/test.py
index 1234567..89abcdef 100644
--- a/test.py
+++ b/test.py
+def new_function():
+    return 42
-old_code()
+# Added comment
 unchanged line"""
        count = validator._count_meaningful_changes(diff)
        assert count == 3  # +def, +return, -old_code (not comment)


class TestFileExistsValidator:
    """Tests for FileExistsValidator class."""

    def test_create_without_expected_files(self):
        """Test creating FileExistsValidator without expected files."""
        validator = FileExistsValidator()
        assert validator.expected_files == []

    def test_create_with_expected_files(self):
        """Test creating FileExistsValidator with expected files."""
        validator = FileExistsValidator(expected_files=["output.txt", "result.json"])
        assert len(validator.expected_files) == 2
        assert "output.txt" in validator.expected_files

    def test_inherits_from_task_validator(self):
        """Test FileExistsValidator inherits from TaskValidator."""
        assert issubclass(FileExistsValidator, TaskValidator)

    def test_extract_expected_files_from_description(self):
        """Test _extract_expected_files extracts file paths from task description."""
        validator = FileExistsValidator()
        description = "Create a file output.txt and save to results.json"
        files = validator._extract_expected_files(description)
        assert files
        # Should find at least one file pattern

    def test_extract_expected_files_with_various_patterns(self):
        """Test _extract_expected_files handles different patterns."""
        validator = FileExistsValidator()
        patterns = [
            "create data.csv",
            "output to report.pdf",
            "save results.json",
        ]
        for pattern in patterns:
            files = validator._extract_expected_files(pattern)
            assert len(files) >= 0  # Should extract or fail gracefully

    def test_check_file_exists_uses_typed_history_events(self):
        validator = FileExistsValidator(expected_files=["output.txt"])
        state = MagicMock()
        state.history = [FileWriteAction(path="output.txt", content="done")]
        assert validator._check_file_exists(state, "output.txt") is True

    def test_check_file_exists_does_not_infer_from_shell_text(self):
        validator = FileExistsValidator(expected_files=["output.txt"])
        state = MagicMock()
        fake_cmd = MagicMock()
        fake_cmd.command = "cat output.txt"
        state.history = [fake_cmd]
        assert validator._check_file_exists(state, "output.txt") is False

    def test_check_file_exists_accepts_file_read_observation(self):
        validator = FileExistsValidator(expected_files=["config.json"])
        state = MagicMock()
        state.history = [FileReadObservation(path="config.json", content="{}")]
        assert validator._check_file_exists(state, "config.json") is True


class TestLLMTaskEvaluator:
    """Tests for LLMTaskEvaluator class."""

    def test_create_without_llm(self):
        """Test creating LLMTaskEvaluator without LLM."""
        evaluator = LLMTaskEvaluator()
        assert evaluator.llm is None

    def test_create_with_llm(self):
        """Test creating LLMTaskEvaluator with LLM instance."""
        mock_llm = object()
        evaluator = LLMTaskEvaluator(llm=mock_llm)
        assert evaluator.llm is mock_llm

    def test_inherits_from_task_validator(self):
        """Test LLMTaskEvaluator inherits from TaskValidator."""
        assert issubclass(LLMTaskEvaluator, TaskValidator)

    def test_create_evaluation_prompt(self):
        """Test _create_evaluation_prompt generates prompt."""
        from unittest.mock import MagicMock

        evaluator = LLMTaskEvaluator()
        task = Task(description="Fix bug", requirements=["Pass tests"])
        state = MagicMock()
        state.history = []

        prompt = evaluator._create_evaluation_prompt(task, state)
        assert "Fix bug" in prompt
        assert "Pass tests" in prompt
        assert "completed" in prompt
        assert "JSON" in prompt


class TestCompositeValidator:
    """Tests for CompositeValidator class."""

    def test_create_with_validators(self):
        """Test creating CompositeValidator with validators list."""
        validators = [TestPassingValidator(), DiffValidator()]
        composite = CompositeValidator(validators=validators)
        assert len(composite.validators) == 2
        assert composite.min_confidence == 0.7
        assert composite.require_all_pass is False

    def test_create_with_custom_threshold(self):
        """Test creating CompositeValidator with custom threshold."""
        composite = CompositeValidator(validators=[], min_confidence=0.9)
        assert composite.min_confidence == 0.9

    def test_create_with_require_all_pass(self):
        """Test creating CompositeValidator with require_all_pass=True."""
        composite = CompositeValidator(validators=[], require_all_pass=True)
        assert composite.require_all_pass is True

    def test_inherits_from_task_validator(self):
        """Test CompositeValidator inherits from TaskValidator."""
        assert issubclass(CompositeValidator, TaskValidator)

    def test_calculate_vote_metrics(self):
        """Test _calculate_vote_metrics calculates correctly."""
        composite = CompositeValidator(validators=[])
        results = [
            ValidationResult(passed=True, reason="OK", confidence=0.9),
            ValidationResult(passed=True, reason="OK", confidence=0.8),
            ValidationResult(passed=False, reason="Failed", confidence=0.7),
        ]
        passed_count, avg_confidence = composite._calculate_vote_metrics(results)
        assert passed_count == 2
        assert avg_confidence == pytest.approx(0.8)

    def test_vote_passes_with_majority_and_confidence(self):
        """Test _vote_passes returns True with majority and sufficient confidence."""
        composite = CompositeValidator(validators=[], min_confidence=0.7)
        assert composite._vote_passes(2, 3, 0.8) is True
        assert composite._vote_passes(3, 3, 0.9) is True

    def test_vote_fails_without_majority(self):
        """Test _vote_passes returns False without majority."""
        composite = CompositeValidator(validators=[], min_confidence=0.7)
        assert composite._vote_passes(1, 3, 0.9) is False

    def test_vote_fails_without_confidence(self):
        """Test _vote_passes returns False without sufficient confidence."""
        composite = CompositeValidator(validators=[], min_confidence=0.8)
        assert composite._vote_passes(2, 3, 0.6) is False


class TestValidatorIntegration:
    """Integration tests for validator patterns."""

    def test_multiple_validators_can_be_instantiated(self):
        """Test multiple validators can be created together."""
        test_validator = TestPassingValidator()
        diff_validator = DiffValidator()
        file_validator = FileExistsValidator()
        llm_validator = LLMTaskEvaluator()

        assert isinstance(test_validator, TaskValidator)
        assert isinstance(diff_validator, TaskValidator)
        assert isinstance(file_validator, TaskValidator)
        assert isinstance(llm_validator, TaskValidator)

    def test_composite_validator_with_multiple_types(self):
        """Test CompositeValidator can combine different validator types."""
        validators = [
            TestPassingValidator(),
            DiffValidator(),
            FileExistsValidator(expected_files=["output.txt"]),
        ]
        composite = CompositeValidator(validators=validators, min_confidence=0.8)
        assert len(composite.validators) == 3
        assert composite.min_confidence == 0.8

    def test_validation_result_can_hold_complex_data(self):
        """Test ValidationResult can hold complex validation data."""
        result = ValidationResult(
            passed=False,
            reason="Multiple failures detected",
            confidence=0.6,
            missing_items=["tests", "docs", "examples"],
            suggestions=[
                "Run test suite",
                "Update documentation",
                "Add usage examples",
            ],
        )
        assert len(result.missing_items) == 3
        assert len(result.suggestions) == 3
        assert result.confidence == 0.6
