"""Extended tests for backend.validation.task_validator module.

Covers Task, ValidationResult dataclasses and concrete validator classes.
"""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock

from backend.events.action import CmdRunAction
from backend.events.observation import CmdOutputObservation
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


def _make_state(history=None):
    s = MagicMock()
    s.history = history or []
    return s


def _cmd_action(cmd: str) -> MagicMock:
    a = MagicMock(spec=CmdRunAction)
    a.command = cmd
    return a


def _cmd_obs(content: str, exit_code: int = 0) -> MagicMock:
    o = MagicMock(spec=CmdOutputObservation)
    o.content = content
    o.exit_code = exit_code
    return o


class TestTaskDataclass(unittest.TestCase):
    def test_basic(self):
        t = Task(description="do stuff")
        self.assertEqual(t.description, "do stuff")
        self.assertEqual(t.requirements, [])

    def test_with_fields(self):
        t = Task(description="x", requirements=["a"], acceptance_criteria=["b"])
        self.assertEqual(t.requirements, ["a"])


class TestValidationResultDataclass(unittest.TestCase):
    def test_defaults(self):
        r = ValidationResult(passed=True, reason="ok")
        self.assertTrue(r.passed)
        self.assertEqual(r.confidence, 1.0)
        self.assertEqual(r.missing_items, [])

    def test_all_fields(self):
        r = ValidationResult(
            passed=False,
            reason="bad",
            confidence=0.3,
            missing_items=["x"],
            suggestions=["y"],
        )
        self.assertFalse(r.passed)


class TestTestPassingValidatorExt(unittest.IsolatedAsyncioTestCase):
    async def test_no_test_executions(self):
        v = TestPassingValidator()
        result = await v.validate_completion(Task("fix"), _make_state([]))
        self.assertFalse(result.passed)

    async def test_passing_tests(self):
        v = TestPassingValidator()
        result = await v.validate_completion(
            Task("fix"),
            _make_state([_cmd_action("pytest tests/"), _cmd_obs("ok", exit_code=0)]),
        )
        self.assertTrue(result.passed)

    async def test_failing_tests(self):
        v = TestPassingValidator()
        result = await v.validate_completion(
            Task("fix"),
            _make_state([_cmd_action("pytest tests/"), _cmd_obs("FAIL", exit_code=1)]),
        )
        self.assertFalse(result.passed)

    async def test_npm_test_recognized(self):
        v = TestPassingValidator()
        result = await v.validate_completion(
            Task("fix"),
            _make_state([_cmd_action("npm test"), _cmd_obs("ok", exit_code=0)]),
        )
        self.assertTrue(result.passed)


class TestDiffValidatorExt(unittest.IsolatedAsyncioTestCase):
    async def test_no_diff(self):
        v = DiffValidator()
        result = await v.validate_completion(Task("change"), _make_state([]))
        self.assertFalse(result.passed)

    async def test_substantial_diff(self):
        v = DiffValidator()
        diff = "\n".join(
            ["diff --git a/f b/f", "--- a/f", "+++ b/f"]
            + [f"+code_{i}" for i in range(10)]
        )
        result = await v.validate_completion(
            Task("change"), _make_state([_cmd_action("git diff"), _cmd_obs(diff)])
        )
        self.assertTrue(result.passed)

    async def test_trivial_diff(self):
        v = DiffValidator()
        diff = "diff --git a/f b/f\n--- a/f\n+++ b/f\n+x\n-y"
        result = await v.validate_completion(
            Task("change"), _make_state([_cmd_action("git diff"), _cmd_obs(diff)])
        )
        self.assertFalse(result.passed)

    def test_meaningful_change_detection(self):
        v = DiffValidator()
        self.assertTrue(v._is_meaningful_change_line("+code here"))
        self.assertFalse(v._is_meaningful_change_line("  context"))
        self.assertFalse(v._is_meaningful_change_line("+# comment"))

    def test_diff_metadata(self):
        v = DiffValidator()
        self.assertTrue(v._is_diff_metadata("diff --git a/f b/f"))
        self.assertTrue(v._is_diff_metadata("+++ b/file.py"))
        self.assertFalse(v._is_diff_metadata("+real code"))

    def test_comment_detection(self):
        v = DiffValidator()
        self.assertTrue(v._is_comment_line("# comment"))
        self.assertTrue(v._is_comment_line("// comment"))
        self.assertFalse(v._is_comment_line("real code"))


class TestFileExistsValidatorExt(unittest.IsolatedAsyncioTestCase):
    async def test_no_expected_files(self):
        v = FileExistsValidator()
        result = await v.validate_completion(Task("do something"), _make_state([]))
        self.assertTrue(result.passed)

    async def test_missing_file(self):
        v = FileExistsValidator(expected_files=["out.txt"])
        result = await v.validate_completion(Task("gen"), _make_state([]))
        self.assertFalse(result.passed)

    async def test_file_found(self):
        v = FileExistsValidator(expected_files=["out.txt"])
        result = await v.validate_completion(
            Task("gen"), _make_state([_cmd_action("cat out.txt")])
        )
        self.assertTrue(result.passed)

    def test_extract_files(self):
        v = FileExistsValidator()
        self.assertIn(
            "report.csv", v._extract_expected_files('create file "report.csv"')
        )
        self.assertIn("data.json", v._extract_expected_files("save to data.json"))


class TestLLMTaskEvaluatorExt(unittest.IsolatedAsyncioTestCase):
    async def test_no_llm(self):
        v = LLMTaskEvaluator(llm=None)
        result = await v.validate_completion(Task("x"), _make_state([]))
        self.assertTrue(result.passed)

    async def test_llm_success(self):
        import json

        mock_llm = AsyncMock()
        resp = MagicMock()
        resp.choices = [
            MagicMock(
                message=MagicMock(
                    content=json.dumps(
                        {"completed": True, "reason": "done", "confidence": 0.9}
                    )
                )
            )
        ]
        mock_llm.completion = AsyncMock(return_value=resp)
        v = LLMTaskEvaluator(llm=mock_llm)
        result = await v.validate_completion(Task("fix"), _make_state([]))
        self.assertTrue(result.passed)

    async def test_llm_exception(self):
        mock_llm = AsyncMock()
        mock_llm.completion = AsyncMock(side_effect=RuntimeError("oops"))
        v = LLMTaskEvaluator(llm=mock_llm)
        result = await v.validate_completion(Task("x"), _make_state([]))
        self.assertFalse(result.passed)

    async def test_llm_bad_json(self):
        mock_llm = AsyncMock()
        resp = MagicMock()
        resp.choices = [MagicMock(message=MagicMock(content="not json"))]
        mock_llm.completion = AsyncMock(return_value=resp)
        v = LLMTaskEvaluator(llm=mock_llm)
        result = await v.validate_completion(Task("x"), _make_state([]))
        self.assertFalse(result.passed)

    def test_prompt_generation(self):
        v = LLMTaskEvaluator()
        prompt = v._create_evaluation_prompt(
            Task("fix", requirements=["pass"]), _make_state([])
        )
        self.assertIn("fix", prompt)
        self.assertIn("pass", prompt)


class TestCompositeValidatorExt(unittest.IsolatedAsyncioTestCase):
    async def test_no_validators(self):
        cv = CompositeValidator(validators=[])
        result = await cv.validate_completion(Task("x"), _make_state())
        self.assertTrue(result.passed)

    async def test_all_pass_required_pass(self):
        v = MagicMock(spec=TaskValidator)
        v.validate_completion = AsyncMock(
            return_value=ValidationResult(passed=True, reason="ok", confidence=0.9)
        )
        cv = CompositeValidator(validators=[v], require_all_pass=True)
        result = await cv.validate_completion(Task("x"), _make_state())
        self.assertTrue(result.passed)

    async def test_all_pass_required_fail(self):
        v = MagicMock(spec=TaskValidator)
        v.validate_completion = AsyncMock(
            return_value=ValidationResult(
                passed=False, reason="nope", missing_items=["a"]
            )
        )
        cv = CompositeValidator(validators=[v], require_all_pass=True)
        result = await cv.validate_completion(Task("x"), _make_state())
        self.assertFalse(result.passed)

    async def test_weighted_vote_passes(self):
        v1 = MagicMock(spec=TaskValidator)
        v1.validate_completion = AsyncMock(
            return_value=ValidationResult(passed=True, reason="ok", confidence=0.9)
        )
        v2 = MagicMock(spec=TaskValidator)
        v2.validate_completion = AsyncMock(
            return_value=ValidationResult(passed=True, reason="ok", confidence=0.8)
        )
        cv = CompositeValidator(validators=[v1, v2], min_confidence=0.5)
        result = await cv.validate_completion(Task("x"), _make_state())
        self.assertTrue(result.passed)

    async def test_exception_skipped(self):
        v1 = MagicMock(spec=TaskValidator)
        v1.validate_completion = AsyncMock(side_effect=RuntimeError("boom"))
        v1.__class__.__name__ = "Bad"
        v2 = MagicMock(spec=TaskValidator)
        v2.validate_completion = AsyncMock(
            return_value=ValidationResult(passed=True, reason="ok", confidence=0.9)
        )
        cv = CompositeValidator(validators=[v1, v2], min_confidence=0.5)
        result = await cv.validate_completion(Task("x"), _make_state())
        self.assertTrue(result.passed)


if __name__ == "__main__":
    unittest.main()
