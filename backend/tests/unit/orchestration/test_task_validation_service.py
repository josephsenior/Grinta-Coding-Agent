"""Tests for backend.orchestration.services.task_validation_service."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.orchestration.services.task_validation_service import TaskValidationService

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_context(has_validator: bool = True, initial_task: str | None = 'Do X'):
    """Build a fake OrchestrationContext with a mock controller."""
    controller = MagicMock()
    controller._get_initial_task.return_value = initial_task
    controller.event_stream = MagicMock()

    if has_validator:
        controller.task_validator = AsyncMock()
    else:
        controller.task_validator = None

    state_mock = MagicMock()
    state_mock.agent_state = 'running'
    controller.state = state_mock
    controller.set_agent_state_to = AsyncMock()

    ctx = MagicMock()
    ctx.get_controller.return_value = controller
    return ctx


def _make_action(force_finish: bool = False):
    return SimpleNamespace(force_finish=force_finish)


def _validation_result(
    passed: bool,
    reason: str = '',
    confidence: float = 1.0,
    missing_items=None,
    suggestions=None,
):
    return SimpleNamespace(
        passed=passed,
        reason=reason,
        confidence=confidence,
        missing_items=missing_items or [],
        suggestions=suggestions or [],
    )


# ===================================================================
# _should_validate
# ===================================================================


class TestShouldValidate:
    @pytest.mark.asyncio
    async def test_no_validator(self):
        ctx = _make_context(has_validator=False)
        svc = TaskValidationService(ctx)
        action = _make_action()
        assert await svc._should_validate(action) is False

    @pytest.mark.asyncio
    async def test_force_finish_skips_validation(self):
        ctx = _make_context(has_validator=True)
        svc = TaskValidationService(ctx)
        action = _make_action(force_finish=True)
        assert await svc._should_validate(action) is False

    @pytest.mark.asyncio
    async def test_normal_with_validator(self):
        ctx = _make_context(has_validator=True)
        svc = TaskValidationService(ctx)
        action = _make_action(force_finish=False)
        assert await svc._should_validate(action) is True


# ===================================================================
# handle_finish
# ===================================================================


class TestHandleFinish:
    @pytest.mark.asyncio
    async def test_no_validator_returns_true(self):
        ctx = _make_context(has_validator=False)
        svc = TaskValidationService(ctx)
        assert await svc.handle_finish(_make_action()) is True

    @pytest.mark.asyncio
    async def test_force_finish_skips_validation(self):
        ctx = _make_context(has_validator=True)
        svc = TaskValidationService(ctx)
        assert await svc.handle_finish(_make_action(force_finish=True)) is True

    @pytest.mark.asyncio
    async def test_validation_passes(self):
        ctx = _make_context(has_validator=True)
        controller = ctx.get_controller()
        controller.task_validator.validate_completion = AsyncMock(
            return_value=_validation_result(passed=True, reason='All good')
        )
        svc = TaskValidationService(ctx)
        assert await svc.handle_finish(_make_action()) is True

    @pytest.mark.asyncio
    async def test_validation_fails(self):
        ctx = _make_context(has_validator=True)
        controller = ctx.get_controller()
        controller.task_validator.validate_completion = AsyncMock(
            return_value=_validation_result(
                passed=False,
                reason='Tests not written',
                confidence=0.4,
                missing_items=['unit tests'],
            )
        )
        svc = TaskValidationService(ctx)
        result = await svc.handle_finish(_make_action())
        assert result is False
        # Should have emitted an error event
        controller.event_stream.add_event.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_initial_task_returns_true(self):
        ctx = _make_context(has_validator=True, initial_task=None)
        svc = TaskValidationService(ctx)
        # With no task, _validate_and_handle returns True
        controller = ctx.get_controller()
        controller.task_validator.validate_completion = AsyncMock()
        assert await svc.handle_finish(_make_action()) is True


# ===================================================================
# _build_feedback
# ===================================================================


class TestBuildFeedback:
    def test_basic_feedback(self):
        val = _validation_result(passed=False, reason='Incomplete', confidence=0.3)
        feedback = TaskValidationService._build_feedback(val)
        assert 'TASK NOT COMPLETE' in feedback
        assert 'Incomplete' in feedback
        assert '30.0%' in feedback

    def test_with_missing_items(self):
        val = _validation_result(
            passed=False,
            reason='Missing',
            confidence=0.5,
            missing_items=['tests', 'docs'],
        )
        feedback = TaskValidationService._build_feedback(val)
        assert '- tests' in feedback
        assert '- docs' in feedback

    def test_with_suggestions(self):
        val = _validation_result(
            passed=False,
            reason='Needs work',
            confidence=0.6,
            suggestions=['Add error handling', 'Refactor'],
        )
        feedback = TaskValidationService._build_feedback(val)
        assert 'Add error handling' in feedback
        assert 'Refactor' in feedback

    def test_ends_with_continue(self):
        val = _validation_result(passed=False, reason='x', confidence=0.1)
        feedback = TaskValidationService._build_feedback(val)
        assert 'continue working' in feedback
