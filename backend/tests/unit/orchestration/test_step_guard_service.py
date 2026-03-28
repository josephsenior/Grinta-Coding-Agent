"""Tests for backend.orchestration.services.step_guard_service."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, AsyncMock

import pytest

from backend.orchestration.services.step_guard_service import StepGuardService
from backend.core.schemas import AgentState


def _make_service():
    ctx = MagicMock()
    ctx.agent_config = SimpleNamespace(
        warning_first_trip_enabled=False,
        warning_first_trip_limit=3,
    )
    controller = MagicMock()
    controller.event_stream = MagicMock()
    controller.set_agent_state_to = AsyncMock()
    controller._react_to_exception = AsyncMock()
    ctx.get_controller.return_value = controller
    return StepGuardService(ctx), controller


# ── ensure_can_step ──────────────────────────────────────────────────


class TestEnsureCanStep:
    @pytest.mark.asyncio
    async def test_passes_when_no_issues(self):
        svc, ctrl = _make_service()
        ctrl.circuit_breaker_service.check.return_value = SimpleNamespace(tripped=False)
        ctrl.stuck_service.is_stuck.return_value = False
        assert await svc.ensure_can_step() is True

    @pytest.mark.asyncio
    async def test_circuit_breaker_tripped_stop(self):
        svc, ctrl = _make_service()
        ctrl.circuit_breaker_service.check.return_value = SimpleNamespace(
            tripped=True, reason="too many errors", action="stop", recommendation="wait"
        )
        assert await svc.ensure_can_step() is False
        ctrl.set_agent_state_to.assert_awaited_once_with(AgentState.STOPPED)

    @pytest.mark.asyncio
    async def test_circuit_breaker_tripped_pause(self):
        svc, ctrl = _make_service()
        ctrl.circuit_breaker_service.check.return_value = SimpleNamespace(
            tripped=True, reason="rate limit", action="pause", recommendation="slow"
        )
        assert await svc.ensure_can_step() is False
        ctrl.set_agent_state_to.assert_awaited_once_with(AgentState.PAUSED)

    @pytest.mark.asyncio
    async def test_stuck_detection(self):
        svc, ctrl = _make_service()
        ctrl.circuit_breaker_service.check.return_value = SimpleNamespace(tripped=False)
        ctrl.stuck_service.is_stuck.return_value = True
        ctrl.circuit_breaker_service.record_stuck_detection = MagicMock()
        assert await svc.ensure_can_step() is True
        ctrl.circuit_breaker_service.record_stuck_detection.assert_called_once()
        ctrl._react_to_exception.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_no_services(self):
        svc, ctrl = _make_service()
        ctrl.circuit_breaker_service = None
        ctrl.stuck_service = None
        # When there's no circuit_breaker_service, _check_circuit_breaker returns True
        # When there's no stuck_service, _handle_stuck_detection returns True
        assert await svc.ensure_can_step() is True
