"""Tests for RecoveryService."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.controller.services.recovery_service import RecoveryService
from backend.events.observation import ErrorObservation
from backend.llm.exceptions import AuthenticationError, Timeout


@pytest.fixture()
def mock_context():
    ctx = MagicMock()
    ctx.get_controller.return_value = MagicMock()
    ctx.discard_invocation_context_for_action = MagicMock()
    ctx.emit_event = MagicMock()
    ctx.trigger_step = MagicMock()
    return ctx


@pytest.fixture()
def ctrl(mock_context):
    c = mock_context.get_controller.return_value
    c.id = "sid-1"
    c.circuit_breaker_service = MagicMock()
    c.pending_action_service = MagicMock()
    c.pending_action_service.get.return_value = None
    c.retry_service = MagicMock()
    c.retry_service.schedule_retry_after_failure = AsyncMock(return_value=False)
    return c


class TestRecoveryService:
    @pytest.mark.asyncio
    async def test_emits_error_and_triggers_step(self, mock_context, ctrl):
        svc = RecoveryService(mock_context)
        await svc.react_to_exception(Timeout("slow"))

        ctrl.circuit_breaker_service.record_error.assert_called_once()
        mock_context.emit_event.assert_called_once()
        err_obs, source = mock_context.emit_event.call_args[0]
        assert isinstance(err_obs, ErrorObservation)
        assert err_obs.error_id == "LLM_TIMEOUT"
        assert "Timeout" in err_obs.content
        ctrl.retry_service.schedule_retry_after_failure.assert_awaited_once()
        mock_context.trigger_step.assert_called_once_with()

    @pytest.mark.asyncio
    async def test_clears_pending_and_discards_context(self, mock_context, ctrl):
        pending = MagicMock()
        pending.id = 7
        ctrl.pending_action_service.get.return_value = pending

        svc = RecoveryService(mock_context)
        await svc.react_to_exception(RuntimeError("x"))

        mock_context.discard_invocation_context_for_action.assert_called_once_with(
            pending
        )
        ctrl.pending_action_service.set.assert_called_once_with(None)

    @pytest.mark.asyncio
    async def test_no_step_when_retry_scheduled(self, mock_context, ctrl):
        ctrl.retry_service.schedule_retry_after_failure = AsyncMock(return_value=True)

        svc = RecoveryService(mock_context)
        await svc.react_to_exception(Timeout("slow"))

        mock_context.trigger_step.assert_not_called()

    @pytest.mark.asyncio
    async def test_authentication_sets_notify_ui_only(self, mock_context, ctrl):
        svc = RecoveryService(mock_context)
        await svc.react_to_exception(AuthenticationError("bad key"))

        err_obs = mock_context.emit_event.call_args[0][0]
        assert err_obs.notify_ui_only is True
