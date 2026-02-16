"""Unit tests for backend.validation.task_validator — task completion checks."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.events.action import CmdRunAction
from backend.events.observation import CmdOutputObservation
from backend.validation.task_validator import (
    CompositeValidator,
    DiffValidator,
    FileExistsValidator,
    LLMTaskEvaluator,
    Task,
    TestPassingValidator,
    ValidationResult,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_state(history=None):
    state = MagicMock()
    state.history = history or []
    return state


def _make_task(desc="implement feature", reqs=None, criteria=None):
    return Task(
        description=desc,
        requirements=reqs or [],
        acceptance_criteria=criteria or [],
    )


def _cmd_obs_pair(command: str, output: str, exit_code: int = 0):
    """Return (CmdRunAction, CmdOutputObservation) pair."""
    action = CmdRunAction(command=command)
    obs = CmdOutputObservation(content=output, command_id=0, command=command)
    obs.exit_code = exit_code
    return action, obs


# ---------------------------------------------------------------------------
# Task & ValidationResult
# ---------------------------------------------------------------------------


class TestTaskModel:
    def test_defaults(self):
        t = Task(description="do stuff")
        assert t.requirements == []
        assert t.acceptance_criteria == []

    def test_fields(self):
        t = Task(description="d", requirements=["r1"], acceptance_criteria=["c1"])
        assert t.requirements == ["r1"]


class TestValidationResult:
    def test_defaults(self):
        r = ValidationResult(passed=True, reason="ok")
        assert r.confidence == 1.0
        assert r.missing_items == []
        assert r.suggestions == []


# ---------------------------------------------------------------------------
# TestPassingValidator
# ---------------------------------------------------------------------------


class TestTestPassingValidator:
    @pytest.mark.asyncio
    async def test_no_test_runs(self):
        v = TestPassingValidator()
        state = _make_state()
        result = await v.validate_completion(_make_task(), state)
        assert result.passed is False
        assert "no test" in result.reason.lower()

    @pytest.mark.asyncio
    async def test_passing_tests(self):
        a, o = _cmd_obs_pair("pytest", "5 passed", exit_code=0)
        state = _make_state(history=[a, o])
        v = TestPassingValidator()
        result = await v.validate_completion(_make_task(), state)
        assert result.passed is True

    @pytest.mark.asyncio
    async def test_failing_tests(self):
        a, o = _cmd_obs_pair("pytest", "FAILED", exit_code=1)
        state = _make_state(history=[a, o])
        v = TestPassingValidator()
        result = await v.validate_completion(_make_task(), state)
        assert result.passed is False
        assert "failed" in result.reason.lower()

    @pytest.mark.asyncio
    async def test_multiple_test_frameworks(self):
        """npm test also counts as a test run."""
        a, o = _cmd_obs_pair("npm test", "Tests: 10 passed", exit_code=0)
        state = _make_state(history=[a, o])
        v = TestPassingValidator()
        result = await v.validate_completion(_make_task(), state)
        assert result.passed is True


# ---------------------------------------------------------------------------
# DiffValidator
# ---------------------------------------------------------------------------


class TestDiffValidator:
    @pytest.mark.asyncio
    async def test_no_diff(self):
        v = DiffValidator()
        state = _make_state()
        result = await v.validate_completion(_make_task(), state)
        assert result.passed is False
        assert "no git" in result.reason.lower()

    @pytest.mark.asyncio
    async def test_substantial_diff(self):
        diff_lines = "\n".join(
            [f"+line {i}" for i in range(20)]
            + [f"-old_line {i}" for i in range(5)]
        )
        a, o = _cmd_obs_pair("git diff", diff_lines, exit_code=0)
        state = _make_state(history=[a, o])
        v = DiffValidator()
        result = await v.validate_completion(_make_task(), state)
        assert result.passed is True

    @pytest.mark.asyncio
    async def test_tiny_diff(self):
        a, o = _cmd_obs_pair("git diff", "+x=1\n-x=0", exit_code=0)
        state = _make_state(history=[a, o])
        v = DiffValidator()
        result = await v.validate_completion(_make_task(), state)
        assert result.passed is False

    def test_count_meaningful_changes(self):
        v = DiffValidator()
        diff = "diff --git a/f b/f\nindex abc..def\n--- a/f\n+++ b/f\n+real code\n-old code\n # comment line"
        count = v._count_meaningful_changes(diff)
        assert count == 2  # only +real code and -old code

    def test_comment_lines_skipped(self):
        v = DiffValidator()
        assert v._is_comment_line("# this is a comment") is True
        assert v._is_comment_line("// also a comment") is True
        assert v._is_comment_line("real code") is False

    def test_metadata_lines_skipped(self):
        v = DiffValidator()
        assert v._is_diff_metadata("diff --git a/f b/f") is True
        assert v._is_diff_metadata("index 1234..5678") is True
        assert v._is_diff_metadata("--- a/file.py") is True
        assert v._is_diff_metadata("+++ b/file.py") is True
        assert v._is_diff_metadata("+real code") is False


# ---------------------------------------------------------------------------
# FileExistsValidator
# ---------------------------------------------------------------------------


class TestFileExistsValidator:
    @pytest.mark.asyncio
    async def test_no_expected_files(self):
        v = FileExistsValidator()
        state = _make_state()
        result = await v.validate_completion(_make_task("do something"), state)
        # No files to check → passes with low confidence
        assert result.passed is True
        assert result.confidence == 0.5

    @pytest.mark.asyncio
    async def test_expected_file_found(self):
        v = FileExistsValidator(expected_files=["output.txt"])
        a = CmdRunAction(command="cat output.txt")
        state = _make_state(history=[a])
        result = await v.validate_completion(_make_task(), state)
        assert result.passed is True

    @pytest.mark.asyncio
    async def test_expected_file_missing(self):
        v = FileExistsValidator(expected_files=["missing.txt"])
        state = _make_state()
        result = await v.validate_completion(_make_task(), state)
        assert result.passed is False
        assert "missing.txt" in result.reason

    def test_extract_expected_files(self):
        v = FileExistsValidator()
        files = v._extract_expected_files('create a file "output.json" with results')
        assert "output.json" in files

    def test_extract_no_files(self):
        v = FileExistsValidator()
        files = v._extract_expected_files("just do some computation")
        assert files == []


# ---------------------------------------------------------------------------
# LLMTaskEvaluator
# ---------------------------------------------------------------------------


class TestLLMTaskEvaluator:
    @pytest.mark.asyncio
    async def test_no_llm_configured(self):
        v = LLMTaskEvaluator(llm=None)
        result = await v.validate_completion(_make_task(), _make_state())
        assert result.passed is True
        assert result.confidence == 0.5

    @pytest.mark.asyncio
    async def test_llm_exception(self):
        mock_llm = AsyncMock()
        mock_llm.completion.side_effect = RuntimeError("API down")
        v = LLMTaskEvaluator(llm=mock_llm)
        result = await v.validate_completion(_make_task(), _make_state())
        assert result.passed is False

    def test_create_evaluation_prompt(self):
        v = LLMTaskEvaluator()
        task = _make_task("build API", reqs=["endpoint /users"])
        state = _make_state()
        prompt = v._create_evaluation_prompt(task, state)
        assert "build API" in prompt
        assert "/users" in prompt


# ---------------------------------------------------------------------------
# CompositeValidator
# ---------------------------------------------------------------------------


class TestCompositeValidator:
    @pytest.mark.asyncio
    async def test_all_pass_require_all(self):
        v1 = MagicMock(spec=TestPassingValidator)
        v1.validate_completion = AsyncMock(
            return_value=ValidationResult(passed=True, reason="ok", confidence=0.9)
        )
        v2 = MagicMock(spec=DiffValidator)
        v2.validate_completion = AsyncMock(
            return_value=ValidationResult(passed=True, reason="ok", confidence=0.8)
        )
        cv = CompositeValidator([v1, v2], require_all_pass=True)
        result = await cv.validate_completion(_make_task(), _make_state())
        assert result.passed is True
        assert result.confidence == 0.8  # min

    @pytest.mark.asyncio
    async def test_one_fails_require_all(self):
        v1 = MagicMock()
        v1.validate_completion = AsyncMock(
            return_value=ValidationResult(passed=True, reason="ok", confidence=0.9)
        )
        v2 = MagicMock()
        v2.validate_completion = AsyncMock(
            return_value=ValidationResult(
                passed=False, reason="no diff", confidence=0.8, missing_items=["item"]
            )
        )
        cv = CompositeValidator([v1, v2], require_all_pass=True)
        result = await cv.validate_completion(_make_task(), _make_state())
        assert result.passed is False

    @pytest.mark.asyncio
    async def test_weighted_vote_majority(self):
        v1 = MagicMock()
        v1.validate_completion = AsyncMock(
            return_value=ValidationResult(passed=True, reason="ok", confidence=0.9)
        )
        v2 = MagicMock()
        v2.validate_completion = AsyncMock(
            return_value=ValidationResult(passed=True, reason="ok2", confidence=0.8)
        )
        v3 = MagicMock()
        v3.validate_completion = AsyncMock(
            return_value=ValidationResult(passed=False, reason="nope", confidence=0.7)
        )
        cv = CompositeValidator([v1, v2, v3], min_confidence=0.5)
        result = await cv.validate_completion(_make_task(), _make_state())
        assert result.passed is True

    @pytest.mark.asyncio
    async def test_weighted_vote_low_confidence_fails(self):
        v1 = MagicMock()
        v1.validate_completion = AsyncMock(
            return_value=ValidationResult(passed=True, reason="ok", confidence=0.3)
        )
        v2 = MagicMock()
        v2.validate_completion = AsyncMock(
            return_value=ValidationResult(passed=True, reason="ok", confidence=0.2)
        )
        cv = CompositeValidator([v1, v2], min_confidence=0.8)
        result = await cv.validate_completion(_make_task(), _make_state())
        assert result.passed is False

    @pytest.mark.asyncio
    async def test_empty_validators(self):
        cv = CompositeValidator([])
        result = await cv.validate_completion(_make_task(), _make_state())
        assert result.passed is True
        assert result.confidence == 0.0

    @pytest.mark.asyncio
    async def test_validator_exception_handled(self):
        bad = MagicMock()
        bad.validate_completion = AsyncMock(side_effect=RuntimeError("crash"))
        good = MagicMock()
        good.validate_completion = AsyncMock(
            return_value=ValidationResult(passed=True, reason="ok", confidence=0.9)
        )
        cv = CompositeValidator([bad, good])
        result = await cv.validate_completion(_make_task(), _make_state())
        # Only the good validator ran successfully
        assert result.passed is True
