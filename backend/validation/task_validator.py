"""Task completion validation framework.

This module provides pluggable validators to ensure agents don't prematurely
finish tasks. Validators check for test passage, meaningful changes, and
requirement satisfaction.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from backend.orchestration.state.state import State

from backend.core.logger import app_logger as logger
from backend.ledger.action import CmdRunAction
from backend.ledger.action.files import FileEditAction, FileWriteAction
from backend.ledger.observation.files import (
    FileEditObservation,
    FileReadObservation,
    FileWriteObservation,
)
from backend.validation.command_classification import (
    find_cmd_output_for_run,
    is_git_diff_command,
    is_test_run_command,
)


@dataclass
class Task:
    """Represents a task to be completed."""

    description: str
    requirements: list[str] = field(default_factory=list)
    acceptance_criteria: list[str] = field(default_factory=list)
    #: Explicit output paths from structured task metadata (see ``task_metadata``).
    #: ``None`` = not provided; fall back to validator init / prose regex hints.
    expected_output_files: list[str] | None = None


@dataclass
class ValidationResult:
    """Result of task completion validation."""

    passed: bool
    reason: str
    confidence: float = 1.0  # 0.0 to 1.0
    missing_items: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)


class TaskValidator(ABC):
    """Abstract base class for task completion validators."""

    @abstractmethod
    async def validate_completion(self, task: Task, state: State) -> ValidationResult:
        """Validate if a task is complete.

        Args:
            task: The task being validated
            state: Current agent state

        Returns:
            ValidationResult indicating if task is complete

        """


class TestPassingValidator(TaskValidator):
    """Validates that tests are passing before task completion."""

    async def validate_completion(self, task: Task, state: State) -> ValidationResult:
        """Check if tests are passing.

        Looks for test execution in recent history and checks exit codes.

        Args:
            task: The task being validated
            state: Current agent state

        Returns:
            ValidationResult for test status

        """
        # Look for test execution in recent history
        test_executions = self._find_test_executions(state)

        if not test_executions:
            return ValidationResult(
                passed=False,
                reason='No test execution found in recent history',
                confidence=0.8,
                missing_items=['Run test suite to verify changes'],
                suggestions=['Run pytest, npm test, or appropriate test command'],
            )

        # Check if latest tests passed
        latest_test = test_executions[-1]
        if latest_test['exit_code'] != 0:
            return ValidationResult(
                passed=False,
                reason=f'Latest test execution failed with exit code {latest_test["exit_code"]}',
                confidence=1.0,
                missing_items=['Fix failing tests'],
                suggestions=['Review test output and fix the failing tests'],
            )

        logger.info('Test validation passed: tests are passing')
        return ValidationResult(
            passed=True,
            reason='Tests are passing',
            confidence=1.0,
        )

    def _find_test_executions(self, state: State) -> list[dict]:
        """Find test executions in history.

        Args:
            state: Current agent state

        Returns:
            List of test execution information

        """
        test_executions = []
        recent_history = state.history[-50:]  # Look at last 50 events

        for i, event in enumerate(recent_history):
            if isinstance(event, CmdRunAction) and is_test_run_command(event.command):
                paired = find_cmd_output_for_run(event, recent_history, i)
                if paired is not None:
                    test_executions.append(
                        {
                            'command': event.command,
                            'exit_code': paired.exit_code,
                            'output': paired.content,
                        },
                    )

        return test_executions


class DiffValidator(TaskValidator):
    """Validates that meaningful changes were made."""

    async def validate_completion(self, task: Task, state: State) -> ValidationResult:
        """Check if meaningful git changes exist.

        Args:
            task: The task being validated
            state: Current agent state

        Returns:
            ValidationResult for git diff

        """
        # Look for git diff in recent history
        git_diff = self._get_diff_output(state)

        if not git_diff:
            return ValidationResult(
                passed=False,
                reason='No git changes detected',
                confidence=0.9,
                missing_items=['Make code changes to complete the task'],
                suggestions=['Implement the required functionality'],
            )

        # Check if diff is substantial (not just whitespace/comments)
        meaningful_changes = self._count_meaningful_changes(git_diff)

        if meaningful_changes < 5:
            return ValidationResult(
                passed=False,
                reason=f'Only {meaningful_changes} meaningful changes detected (expected at least 5)',
                confidence=0.7,
                missing_items=['Add more substantial changes'],
                suggestions=['Ensure all requirements are implemented'],
            )

        logger.info(
            'Git diff validation passed: %s meaningful changes', meaningful_changes
        )
        return ValidationResult(
            passed=True,
            reason=f'Meaningful changes detected ({meaningful_changes} lines)',
            confidence=0.8,
        )

    def _get_diff_output(self, state: State) -> str | None:
        """Get git diff from history.

        Args:
            state: Current agent state

        Returns:
            Git diff content or None

        """
        recent_history = state.history[-100:]

        for i, event in enumerate(recent_history):
            if isinstance(event, CmdRunAction) and is_git_diff_command(event.command):
                paired = find_cmd_output_for_run(event, recent_history, i)
                if paired is not None:
                    return paired.content

        return None

    def _count_meaningful_changes(self, diff: str) -> int:
        """Count meaningful lines in diff (not whitespace/comments).

        Args:
            diff: Git diff content

        Returns:
            Count of meaningful changed lines

        """
        return sum(
            1 for line in diff.split('\n') if self._is_meaningful_change_line(line)
        )

    def _is_meaningful_change_line(self, line: str) -> bool:
        """Check if line is a meaningful change.

        Args:
            line: Diff line

        Returns:
            True if meaningful change

        """
        # Skip diff metadata
        if self._is_diff_metadata(line):
            return False

        # Check if added/removed line
        if not (line.startswith(('+', '-'))):
            return False

        # Check if content is meaningful
        content = line[1:].strip()
        return bool(content) and not self._is_comment_line(content)

    def _is_diff_metadata(self, line: str) -> bool:
        """Check if line is diff metadata.

        Args:
            line: Diff line

        Returns:
            True if metadata

        """
        return line.startswith(('diff --git', 'index ', '+++', '---'))

    def _is_comment_line(self, content: str) -> bool:
        """Check if content is a comment.

        Args:
            content: Line content

        Returns:
            True if comment

        """
        return content.startswith(('#', '//'))


class FileExistsValidator(TaskValidator):
    """Validates that expected output files exist.

    When ``expected_files`` is empty, ``_extract_expected_files`` uses a small
    set of regexes over the task description. That path is a best-effort hint
    for autonomy-style validation only; prefer passing explicit paths when the
    task definition allows.
    """

    def __init__(self, expected_files: list[str] | None = None) -> None:
        """Initialize validator.

        Args:
            expected_files: List of file paths that should exist

        """
        self.expected_files = expected_files or []

    async def validate_completion(self, task: Task, state: State) -> ValidationResult:
        """Check if expected files exist.

        Args:
            task: The task being validated
            state: Current agent state

        Returns:
            ValidationResult for file existence

        """
        if task.expected_output_files is not None:
            files_to_check = list(task.expected_output_files)
        elif self.expected_files:
            files_to_check = list(self.expected_files)
        else:
            files_to_check = self._extract_expected_files(task.description)

        if not files_to_check:
            logger.debug('FileExistsValidator: No expected files specified')
            return ValidationResult(
                passed=True,
                reason='No expected files specified',
                confidence=0.9 if task.expected_output_files is not None else 0.5,
            )

        missing_files = []
        for file_path in files_to_check:
            if not self._check_file_exists(state, file_path):
                missing_files.append(file_path)

        if missing_files:
            return ValidationResult(
                passed=False,
                reason=f'Expected files not found: {", ".join(missing_files)}',
                confidence=0.9,
                missing_items=[f'Create {file_path}' for file_path in missing_files],
                suggestions=['Create the required output files'],
            )

        logger.info('File existence validation passed: all expected files exist')
        return ValidationResult(
            passed=True,
            reason='All expected files exist',
            confidence=0.9,
        )

    def _extract_expected_files(self, task_description: str) -> list[str]:
        """Try to extract expected file names from task description.

        Best-effort only: prose is ambiguous; prefer explicit structured task
        fields when adding new validation. Patterns are intentionally narrow
        (quoted paths, or explicit create/file/output/save phrasing) to reduce
        false positives from incidental ``word.ext`` mentions in prose.

        Args:
            task_description: Task description text

        Returns:
            List of potential file paths

        """
        file_patterns = [
            r'create\s+(?:a\s+)?file\s+([a-zA-Z0-9_./\\-]+\.[a-zA-Z][a-zA-Z0-9]{0,15})\b',
            r'["\']([a-zA-Z0-9_./\\-]+\.[a-zA-Z][a-zA-Z0-9]{0,15})["\']',
            r'output\s+to\s+([a-zA-Z0-9_./\\-]+\.[a-zA-Z][a-zA-Z0-9]{0,15})\b',
            r'save\s+(?:to\s+)?([a-zA-Z0-9_./\\-]+\.[a-zA-Z][a-zA-Z0-9]{0,15})\b',
        ]

        expected_files = []
        for pattern in file_patterns:
            matches = re.findall(pattern, task_description, re.IGNORECASE)
            expected_files.extend(matches)

        return list(set(expected_files))  # Remove duplicates

    def _check_file_exists(self, state: State, file_path: str) -> bool:
        """Check if file exists using typed file events from history.

        Args:
            state: Current agent state
            file_path: Path to check

        Returns:
            True if file appears to exist

        """

        def _normalize_path(path: str) -> str:
            normalized = path.replace('\\', '/').strip('/')
            if normalized.startswith('workspace/'):
                normalized = normalized[len('workspace/') :]
            return normalized

        recent_history = state.history[-100:]
        expected = _normalize_path(file_path)
        for event in recent_history:
            event_path = getattr(event, 'path', None)
            if (
                not isinstance(event_path, str)
                or _normalize_path(event_path) != expected
            ):
                continue
            if isinstance(
                event,
                (
                    FileEditAction,
                    FileWriteAction,
                    FileEditObservation,
                    FileWriteObservation,
                    FileReadObservation,
                ),
            ):
                return True
        return False


class LLMTaskEvaluator(TaskValidator):
    """Uses LLM to evaluate if task requirements are met."""

    def __init__(self, llm=None) -> None:
        """Initialize evaluator.

        Args:
            llm: LLM instance for evaluation (optional)

        """
        self.llm = llm

    async def validate_completion(self, task: Task, state: State) -> ValidationResult:
        """Use LLM to evaluate task completion.

        Args:
            task: The task being validated
            state: Current agent state

        Returns:
            ValidationResult from LLM evaluation

        """
        if not self.llm:
            logger.debug('LLMTaskEvaluator: No LLM configured, skipping')
            return ValidationResult(
                passed=True,
                reason='LLM evaluation not configured',
                confidence=0.5,
            )

        # Create evaluation prompt
        prompt = self._create_evaluation_prompt(task, state)

        try:
            # Get LLM evaluation
            response = await self.llm.completion(
                messages=[{'role': 'user', 'content': prompt}],
                temperature=0.3,
            )

            # Parse LLM response
            return self._parse_llm_response(response)

        except Exception as e:
            logger.error('LLM evaluation failed: %s', e)
            return ValidationResult(
                passed=False,
                reason=f'LLM evaluation failed: {e}',
                confidence=0.1,
            )

    def _create_evaluation_prompt(self, task: Task, state: State) -> str:
        """Create prompt for LLM evaluation.

        Args:
            task: The task
            state: Current state

        Returns:
            Evaluation prompt

        """
        recent_actions = self._get_recent_actions_summary(state)

        return f"""Evaluate if the following task has been completed satisfactorily:

TASK: {task.description}

REQUIREMENTS:
{chr(10).join(f'- {req}' for req in task.requirements) if task.requirements else 'None specified'}

RECENT ACTIONS:
{recent_actions}

Has this task been completed? Respond in JSON format:
{{
    "completed": true/false,
    "reason": "explanation",
    "confidence": 0.0-1.0,
    "missing_items": ["item1", "item2"]
}}
"""

    def _get_recent_actions_summary(self, state: State) -> str:
        """Summarize recent actions.

        Args:
            state: Current state

        Returns:
            Summary string

        """
        recent_history = state.history[-20:]
        actions = [event for event in recent_history if isinstance(event, CmdRunAction)]

        if not actions:
            return 'No recent actions'

        return '\n'.join(f'- {action.command[:100]}' for action in actions[:10])

    def _parse_llm_response(self, response) -> ValidationResult:
        """Parse LLM response into ValidationResult.

        Args:
            response: LLM response

        Returns:
            ValidationResult

        """
        import json

        try:
            # Extract JSON from response
            choices = getattr(response, 'choices', None)
            if not choices or len(choices) == 0:
                return ValidationResult(
                    passed=False,
                    reason='LLM evaluation returned no choices',
                    confidence=0.1,
                )
            content = choices[0].message.content
            if content is None:
                return ValidationResult(
                    passed=False,
                    reason='LLM evaluation choice has no content',
                    confidence=0.1,
                )
            data = json.loads(content)

            return ValidationResult(
                passed=data.get('completed', False),
                reason=data.get('reason', 'LLM evaluation'),
                confidence=data.get('confidence', 0.5),
                missing_items=data.get('missing_items', []),
            )
        except Exception as exc:
            logger.warning('Could not parse LLM evaluation response: %s', exc)
            return ValidationResult(
                passed=False,
                reason=f'Could not parse LLM response: {exc}',
                confidence=0.1,
            )


class CompositeValidator(TaskValidator):
    """Combines multiple validators with configurable thresholds."""

    def __init__(
        self,
        validators: list[TaskValidator],
        min_confidence: float = 0.7,
        require_all_pass: bool = False,
        fail_open_on_empty: bool = True,
    ) -> None:
        """Initialize composite validator.

        Args:
            validators: List of validators to run
            min_confidence: Minimum confidence threshold to pass
            require_all_pass: If True, all validators must pass
            fail_open_on_empty: If True, return passed=True when no validators
                can run successfully. If False, fail closed.

        """
        self.validators = validators
        self.min_confidence = min_confidence
        self.require_all_pass = require_all_pass
        self.fail_open_on_empty = fail_open_on_empty

    async def validate_completion(self, task: Task, state: State) -> ValidationResult:
        """Run all validators and combine results.

        Args:
            task: The task being validated
            state: Current agent state

        Returns:
            Combined ValidationResult

        """
        results = await self._run_all_validators(task, state)

        if not results:
            if not self.fail_open_on_empty:
                return ValidationResult(
                    passed=False,
                    reason='No validators ran successfully',
                    confidence=0.0,
                    missing_items=['Run validation checks before finishing'],
                    suggestions=[
                        'Ensure validator prerequisites are met (tests, diff, files)',
                    ],
                )
            return ValidationResult(
                passed=True, reason='No validators ran successfully', confidence=0.0
            )

        if self.require_all_pass:
            return self._validate_all_must_pass(results)
        return self._validate_weighted_vote(results)

    async def _run_all_validators(
        self, task: Task, state: State
    ) -> list[ValidationResult]:
        """Run all validators and collect results.

        Args:
            task: Task to validate
            state: Agent state

        Returns:
            List of validation results

        """
        results = []
        for validator in self.validators:
            try:
                result = await validator.validate_completion(task, state)
                results.append(result)
            except Exception as e:
                logger.error('Validator %s failed: %s', validator.__class__.__name__, e)
        return results

    def _validate_all_must_pass(
        self, results: list[ValidationResult]
    ) -> ValidationResult:
        """Validate with all-must-pass strategy.

        Args:
            results: List of validation results

        Returns:
            Combined validation result

        """
        all_passed = all(r.passed for r in results)
        combined_confidence = min(r.confidence for r in results) if results else 0.0

        if not all_passed:
            return self._build_all_pass_failure(results, combined_confidence)

        return ValidationResult(
            passed=True,
            reason=f'All validators passed: {len(results)} validators',
            confidence=combined_confidence,
        )

    def _build_all_pass_failure(
        self, results: list[ValidationResult], confidence: float
    ) -> ValidationResult:
        """Build failure result for all-must-pass validation.

        Args:
            results: Validation results
            confidence: Combined confidence

        Returns:
            Failure ValidationResult

        """
        failed_validators = [r for r in results if not r.passed]

        return ValidationResult(
            passed=False,
            reason=f'{len(failed_validators)} validator(s) failed',
            confidence=confidence,
            missing_items=[item for r in failed_validators for item in r.missing_items],
            suggestions=[sug for r in failed_validators for sug in r.suggestions],
        )

    def _validate_weighted_vote(
        self, results: list[ValidationResult]
    ) -> ValidationResult:
        """Validate with weighted voting strategy.

        Args:
            results: List of validation results

        Returns:
            Combined validation result

        """
        passed_count, avg_confidence = self._calculate_vote_metrics(results)

        if self._vote_passes(passed_count, len(results), avg_confidence):
            return ValidationResult(
                passed=True,
                reason=f'All validators passed: {len(results)} validators',
                confidence=avg_confidence,
            )

        return self._build_weighted_vote_failure(results, passed_count, avg_confidence)

    def _calculate_vote_metrics(
        self, results: list[ValidationResult]
    ) -> tuple[int, float]:
        """Calculate voting metrics.

        Args:
            results: Validation results

        Returns:
            Tuple of (passed_count, avg_confidence)

        """
        passed_count = sum(1 for r in results if r.passed)
        avg_confidence = sum(r.confidence for r in results) / len(results)
        return passed_count, avg_confidence

    def _vote_passes(
        self, passed_count: int, total_count: int, avg_confidence: float
    ) -> bool:
        """Check if weighted vote passes.

        Args:
            passed_count: Number of passed validators
            total_count: Total number of validators
            avg_confidence: Average confidence

        Returns:
            True if vote passes

        """
        majority_pass = (passed_count / total_count) >= 0.5
        confidence_check = avg_confidence >= self.min_confidence
        return majority_pass and confidence_check

    def _build_weighted_vote_failure(
        self,
        results: list[ValidationResult],
        passed_count: int,
        avg_confidence: float,
    ) -> ValidationResult:
        """Build failure result for weighted vote validation.

        Args:
            results: Validation results
            passed_count: Number passed
            avg_confidence: Average confidence

        Returns:
            Failure ValidationResult

        """
        failed_validators = [r for r in results if not r.passed]

        return ValidationResult(
            passed=False,
            reason=f'Task validation insufficient: {passed_count}/{
                len(results)
            } passed, avg confidence: {avg_confidence:.2f}',
            confidence=avg_confidence,
            missing_items=[item for r in failed_validators for item in r.missing_items],
            suggestions=[sug for r in failed_validators for sug in r.suggestions],
        )
