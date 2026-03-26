"""Tests for backend.validation.task_validator — task completion validators."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock


from backend.validation.task_validator import (
    CompositeValidator,
    DiffValidator,
    FileExistsValidator,
    LLMTaskEvaluator,
    Task,
    TestPassingValidator,
    ValidationResult,
)
from backend.core.enums import FileReadSource
from backend.events.action import CmdRunAction
from backend.events.observation import CmdOutputObservation
from backend.events.observation.files import FileReadObservation, FileWriteObservation


# ---------------------------------------------------------------------------
# Task & ValidationResult dataclasses
# ---------------------------------------------------------------------------


class TestTaskDataclass:
    def test_defaults(self):
        t = Task(description="Build feature X")
        assert t.description == "Build feature X"
        assert t.requirements == []
        assert t.acceptance_criteria == []
        assert t.expected_output_files is None

    def test_custom(self):
        t = Task(
            description="Fix bug",
            requirements=["unit tests"],
            acceptance_criteria=["no regression"],
        )
        assert len(t.requirements) == 1


class TestValidationResult:
    def test_passed(self):
        r = ValidationResult(passed=True, reason="ok")
        assert r.passed is True
        assert r.confidence == 1.0
        assert r.missing_items == []
        assert r.suggestions == []

    def test_failed_with_details(self):
        r = ValidationResult(
            passed=False,
            reason="tests fail",
            confidence=0.8,
            missing_items=["fix tests"],
            suggestions=["run pytest"],
        )
        assert r.passed is False
        assert len(r.missing_items) == 1


# ---------------------------------------------------------------------------
# TestPassingValidator
# ---------------------------------------------------------------------------


class TestTestPassingValidator:
    def _make_state(self, events):
        state = MagicMock()
        state.history = events
        return state

    async def test_no_test_execution(self):
        v = TestPassingValidator()
        state = self._make_state([])
        result = await v.validate_completion(Task(description="x"), state)
        assert result.passed is False
        assert "No test execution" in result.reason

    async def test_failing_tests(self):
        v = TestPassingValidator()
        cmd = CmdRunAction(command="pytest tests/")
        obs = CmdOutputObservation(
            content="FAILED", command_id=1, command="pytest tests/", exit_code=1
        )
        state = self._make_state([cmd, obs])
        result = await v.validate_completion(Task(description="x"), state)
        assert result.passed is False
        assert "failed" in result.reason.lower()

    async def test_passing_tests(self):
        v = TestPassingValidator()
        cmd = CmdRunAction(command="pytest tests/")
        obs = CmdOutputObservation(
            content="3 passed", command_id=1, command="pytest tests/", exit_code=0
        )
        state = self._make_state([cmd, obs])
        result = await v.validate_completion(Task(description="x"), state)
        assert result.passed is True


# ---------------------------------------------------------------------------
# DiffValidator
# ---------------------------------------------------------------------------


class TestDiffValidator:
    def _make_state(self, events):
        state = MagicMock()
        state.history = events
        return state

    async def test_no_diff(self):
        v = DiffValidator()
        state = self._make_state([])
        result = await v.validate_completion(Task(description="x"), state)
        assert result.passed is False
        assert "No git changes" in result.reason

    async def test_small_diff(self):
        v = DiffValidator()
        cmd = CmdRunAction(command="git diff")
        # Only 2 meaningful lines
        diff_text = "+line1\n+line2\n"
        obs = CmdOutputObservation(
            content=diff_text, command_id=1, command="git diff", exit_code=0
        )
        state = self._make_state([cmd, obs])
        result = await v.validate_completion(Task(description="x"), state)
        assert result.passed is False

    async def test_large_diff(self):
        v = DiffValidator()
        cmd = CmdRunAction(command="git diff")
        diff_text = "\n".join([f"+code_line_{i}" for i in range(10)])
        obs = CmdOutputObservation(
            content=diff_text, command_id=1, command="git diff", exit_code=0
        )
        state = self._make_state([cmd, obs])
        result = await v.validate_completion(Task(description="x"), state)
        assert result.passed is True

    def test_count_meaningful_changes_skips_comments(self):
        v = DiffValidator()
        diff = "+# comment\n+real code\n-# old comment\n-deleted code\n"
        assert v._count_meaningful_changes(diff) == 2

    def test_is_diff_metadata(self):
        v = DiffValidator()
        assert v._is_diff_metadata("diff --git a/f b/f") is True
        assert v._is_diff_metadata("index abc..def") is True
        assert v._is_diff_metadata("+++ b/file.py") is True
        assert v._is_diff_metadata("+real line") is False


# ---------------------------------------------------------------------------
# FileExistsValidator
# ---------------------------------------------------------------------------


class TestFileExistsValidator:
    def _make_state(self, events):
        state = MagicMock()
        state.history = events
        return state

    async def test_no_expected_files(self):
        v = FileExistsValidator()
        state = self._make_state([])
        result = await v.validate_completion(Task(description="do something"), state)
        # Should pass when no expected files determined
        assert result.passed is True
        assert result.confidence == 0.5

    async def test_expected_files_found(self):
        v = FileExistsValidator(expected_files=["main.py"])
        # Existence is proven from typed file events, not shell commands.
        ev = FileReadObservation(
            path="main.py",
            content="ok",
            impl_source=FileReadSource.DEFAULT,
        )
        state = self._make_state([ev])
        result = await v.validate_completion(Task(description="x"), state)
        assert result.passed is True

    async def test_expected_files_not_found(self):
        v = FileExistsValidator(expected_files=["missing.py"])
        state = self._make_state([])
        result = await v.validate_completion(Task(description="x"), state)
        assert result.passed is False
        assert "missing.py" in result.reason

    def test_extract_expected_files(self):
        v = FileExistsValidator()
        files = v._extract_expected_files(
            "Create a file 'main.py' and save to 'output.txt'"
        )
        assert "main.py" in files or "output.txt" in files

    async def test_expected_output_files_on_task_skips_prose_regex(self):
        v = FileExistsValidator()
        ev = FileWriteObservation(path="out.txt", content="ok")
        state = self._make_state([ev])
        task = Task(
            description='Quoted "ghost.json" should not be required',
            expected_output_files=["out.txt"],
        )
        result = await v.validate_completion(task, state)
        assert result.passed is True

    async def test_explicit_empty_expected_output_files_high_confidence(self):
        v = FileExistsValidator()
        state = self._make_state([])
        task = Task(description="any", expected_output_files=[])
        result = await v.validate_completion(task, state)
        assert result.passed is True
        assert result.confidence == 0.9


# ---------------------------------------------------------------------------
# LLMTaskEvaluator
# ---------------------------------------------------------------------------


class TestLLMTaskEvaluator:
    async def test_no_llm_passes(self):
        v = LLMTaskEvaluator(llm=None)
        state = MagicMock()
        state.history = []
        result = await v.validate_completion(Task(description="x"), state)
        assert result.passed is True
        assert result.confidence == 0.5

    async def test_llm_evaluation_success(self):
        import json

        llm = MagicMock()
        choice = MagicMock()
        choice.message.content = json.dumps(
            {
                "completed": True,
                "reason": "All done",
                "confidence": 0.9,
                "missing_items": [],
            }
        )
        resp = MagicMock()
        resp.choices = [choice]
        llm.completion = AsyncMock(return_value=resp)

        v = LLMTaskEvaluator(llm=llm)
        state = MagicMock()
        state.history = []
        result = await v.validate_completion(Task(description="build it"), state)
        assert result.passed is True
        assert result.confidence == 0.9

    async def test_llm_evaluation_failure(self):
        llm = MagicMock()
        llm.completion = AsyncMock(side_effect=RuntimeError("LLM down"))
        v = LLMTaskEvaluator(llm=llm)
        state = MagicMock()
        state.history = []
        result = await v.validate_completion(Task(description="x"), state)
        assert result.passed is False

    def test_llm_parse_response_invalid_json(self):
        v = LLMTaskEvaluator(llm=MagicMock())
        response = MagicMock()
        choice = MagicMock()
        choice.message.content = "not json"
        response.choices = [choice]

        result = v._parse_llm_response(response)

        assert result.passed is False
        assert result.confidence == 0.1
        assert "Could not parse" in result.reason

    def test_recent_actions_summary_no_actions(self):
        v = LLMTaskEvaluator(llm=MagicMock())
        state = MagicMock()
        state.history = []
        summary = v._get_recent_actions_summary(state)
        assert summary == "No recent actions"

    def test_recent_actions_summary_with_actions(self):
        v = LLMTaskEvaluator(llm=MagicMock())
        state = MagicMock()
        state.history = [CmdRunAction(command="pytest tests/")]
        summary = v._get_recent_actions_summary(state)
        assert "pytest tests/" in summary


# ---------------------------------------------------------------------------
# CompositeValidator
# ---------------------------------------------------------------------------


class TestCompositeValidator:
    def _make_validator(self, passed: bool, confidence: float = 1.0):
        v = MagicMock()
        v.validate_completion = AsyncMock(
            return_value=ValidationResult(
                passed=passed,
                reason="test",
                confidence=confidence,
                missing_items=[] if passed else ["fix it"],
                suggestions=[] if passed else ["try harder"],
            )
        )
        return v

    async def test_all_pass_require_all(self):
        v1 = self._make_validator(True, 0.9)
        v2 = self._make_validator(True, 0.8)
        comp = CompositeValidator([v1, v2], require_all_pass=True)
        state = MagicMock()
        state.history = []
        result = await comp.validate_completion(Task(description="x"), state)
        assert result.passed is True

    async def test_one_fails_require_all(self):
        v1 = self._make_validator(True)
        v2 = self._make_validator(False)
        comp = CompositeValidator([v1, v2], require_all_pass=True)
        state = MagicMock()
        state.history = []
        result = await comp.validate_completion(Task(description="x"), state)
        assert result.passed is False

    async def test_majority_vote(self):
        v1 = self._make_validator(True, 0.9)
        v2 = self._make_validator(True, 0.8)
        v3 = self._make_validator(False, 0.7)
        comp = CompositeValidator([v1, v2, v3], min_confidence=0.7)
        state = MagicMock()
        state.history = []
        result = await comp.validate_completion(Task(description="x"), state)
        assert result.passed is True

    async def test_majority_fails(self):
        v1 = self._make_validator(False, 0.3)
        v2 = self._make_validator(False, 0.4)
        v3 = self._make_validator(True, 0.9)
        comp = CompositeValidator([v1, v2, v3], min_confidence=0.7)
        state = MagicMock()
        state.history = []
        result = await comp.validate_completion(Task(description="x"), state)
        assert result.passed is False

    async def test_no_validators(self):
        comp = CompositeValidator([])
        state = MagicMock()
        state.history = []
        result = await comp.validate_completion(Task(description="x"), state)
        assert result.passed is True
        assert result.confidence == 0.0

    async def test_low_confidence_fails_vote(self):
        v1 = self._make_validator(True, 0.3)
        v2 = self._make_validator(True, 0.2)
        comp = CompositeValidator([v1, v2], min_confidence=0.7)
        state = MagicMock()
        state.history = []
        result = await comp.validate_completion(Task(description="x"), state)
        assert result.passed is False

    async def test_validator_exception_is_caught(self):
        good = self._make_validator(True, 0.9)
        bad = MagicMock()
        bad.validate_completion = AsyncMock(side_effect=RuntimeError("boom"))

        comp = CompositeValidator([bad, good])
        state = MagicMock()
        state.history = []

        results = await comp._run_all_validators(Task(description="x"), state)
        assert len(results) == 1
