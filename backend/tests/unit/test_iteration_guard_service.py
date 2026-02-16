"""Tests for backend.controller.services.iteration_guard_service."""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch, AsyncMock

import pytest

from backend.controller.services.iteration_guard_service import IterationGuardService


# ── helpers ──────────────────────────────────────────────────────────

def _make_service() -> tuple[IterationGuardService, MagicMock]:
    context = MagicMock()
    controller = MagicMock()
    controller.state_tracker.run_control_flags = MagicMock()
    controller.state.iteration_flag.current_value = 5
    context.get_controller.return_value = controller
    svc = IterationGuardService(context)
    return svc, controller


# ── _is_limit_error ──────────────────────────────────────────────────

class TestIsLimitError:
    def test_limit_keyword(self):
        svc, _ = _make_service()
        assert svc._is_limit_error("iteration limit exceeded")

    def test_budget_keyword(self):
        svc, _ = _make_service()
        assert svc._is_limit_error("budget exceeded")

    def test_no_match(self):
        svc, _ = _make_service()
        assert not svc._is_limit_error("some other error")


# ── _graceful_shutdown_enabled ───────────────────────────────────────

class TestGracefulShutdownEnabled:
    def test_default_enabled(self):
        svc, ctrl = _make_service()
        ctrl.agent_config = None
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("FORGE_GRACEFUL_SHUTDOWN", None)
            assert svc._graceful_shutdown_enabled() is True

    def test_disabled_by_env(self):
        svc, ctrl = _make_service()
        ctrl.agent_config = None
        with patch.dict(os.environ, {"FORGE_GRACEFUL_SHUTDOWN": "0"}):
            assert svc._graceful_shutdown_enabled() is False

    def test_disabled_by_config(self):
        svc, ctrl = _make_service()
        ctrl.agent_config = MagicMock()
        ctrl.agent_config.enable_graceful_shutdown = False
        assert svc._graceful_shutdown_enabled() is False


# ── run_control_flags ────────────────────────────────────────────────

class TestRunControlFlags:
    @pytest.mark.asyncio
    async def test_success(self):
        svc, ctrl = _make_service()
        await svc.run_control_flags()
        ctrl.state_tracker.run_control_flags.assert_called_once()

    @pytest.mark.asyncio
    async def test_limit_error_schedules_shutdown(self):
        svc, ctrl = _make_service()
        ctrl.state_tracker.run_control_flags.side_effect = RuntimeError("iteration limit")
        with patch.object(svc, "_schedule_graceful_shutdown") as mock_shutdown:
            with pytest.raises(RuntimeError):
                await svc.run_control_flags()
            mock_shutdown.assert_called_once()

    @pytest.mark.asyncio
    async def test_non_limit_error_no_shutdown(self):
        svc, ctrl = _make_service()
        ctrl.state_tracker.run_control_flags.side_effect = RuntimeError("just broken")
        with patch.object(svc, "_schedule_graceful_shutdown") as mock_shutdown:
            with pytest.raises(RuntimeError):
                await svc.run_control_flags()
            mock_shutdown.assert_not_called()
