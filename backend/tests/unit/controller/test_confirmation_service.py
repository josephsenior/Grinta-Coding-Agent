"""Tests for backend.controller.services.confirmation_service."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from typing import cast

import pytest

from backend.controller.services.confirmation_service import ConfirmationService
from backend.core.schemas import AgentState
from backend.events import EventSource
from backend.events.action import ActionConfirmationStatus
from backend.events.action.action import Action


def _make_context(**overrides) -> MagicMock:
    controller = MagicMock()
    controller._replay_manager = MagicMock()
    controller._replay_manager.should_replay.return_value = False
    controller._replay_manager.replay_mode = False
    controller.state = MagicMock()
    controller.state.confirmation_mode = overrides.get("confirmation_mode", False)
    ctx = MagicMock()
    ctx.get_controller.return_value = controller
    ctx.set_agent_state = AsyncMock()
    return ctx


def _make_safety_service() -> MagicMock:
    ss = MagicMock()
    ss.action_requires_confirmation.return_value = False
    ss.analyze_security = AsyncMock()
    ss.evaluate_security_risk.return_value = (False, False)
    return ss


# ── get_next_action ──────────────────────────────────────────────────


class TestGetNextAction:
    def test_live_action(self):
        ctx = _make_context()
        controller = ctx.get_controller()
        controller._replay_manager.should_replay.return_value = False
        action = SimpleNamespace(source=None)
        controller.agent.step.return_value = action
        svc = ConfirmationService(ctx, _make_safety_service())
        result = svc.get_next_action()
        assert result is action
        assert action.source == EventSource.AGENT

    def test_live_action_increments_counter(self):
        ctx = _make_context()
        controller = ctx.get_controller()
        controller._replay_manager.should_replay.return_value = False
        controller.agent.step.return_value = SimpleNamespace(source=None)
        svc = ConfirmationService(ctx, _make_safety_service())
        svc.get_next_action()
        svc.get_next_action()
        assert svc.action_counts["live_actions"] == 2

    def test_replay_action(self):
        ctx = _make_context()
        controller = ctx.get_controller()
        controller._replay_manager.should_replay.return_value = True
        replayed = SimpleNamespace(id=99)
        controller._replay_manager.step.return_value = replayed
        controller._replay_manager.replay_index = 0
        svc = ConfirmationService(ctx, _make_safety_service())
        result = svc.get_next_action()
        assert result is replayed
        assert svc.action_counts["replay_actions"] == 1


# ── is_replay_mode / replay_progress ─────────────────────────────────


class TestReplayProperties:
    def test_not_in_replay(self):
        ctx = _make_context()
        ctx.get_controller()._replay_manager.replay_mode = False
        svc = ConfirmationService(ctx, _make_safety_service())
        assert svc.is_replay_mode is False
        assert svc.replay_progress is None

    def test_in_replay(self):
        ctx = _make_context()
        rm = ctx.get_controller()._replay_manager
        rm.replay_mode = True
        rm.replay_events = [1, 2, 3]
        rm.replay_index = 1
        svc = ConfirmationService(ctx, _make_safety_service())
        assert svc.is_replay_mode is True
        assert svc.replay_progress == (1, 3)


# ── evaluate_action ──────────────────────────────────────────────────


class TestEvaluateAction:
    @pytest.mark.asyncio
    async def test_skips_when_not_confirmation_mode(self):
        ctx = _make_context(confirmation_mode=False)
        ss = _make_safety_service()
        svc = ConfirmationService(ctx, ss)
        await svc.evaluate_action(cast(Action, SimpleNamespace()))
        ss.action_requires_confirmation.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_non_confirmable(self):
        ctx = _make_context(confirmation_mode=True)
        ss = _make_safety_service()
        ss.action_requires_confirmation.return_value = False
        svc = ConfirmationService(ctx, ss)
        await svc.evaluate_action(cast(Action, SimpleNamespace()))
        ss.analyze_security.assert_not_called()

    @pytest.mark.asyncio
    async def test_runs_full_pipeline(self):
        ctx = _make_context(confirmation_mode=True)
        ss = _make_safety_service()
        ss.action_requires_confirmation.return_value = True
        svc = ConfirmationService(ctx, ss)
        action = cast(Action, SimpleNamespace())
        await svc.evaluate_action(action)
        ss.analyze_security.assert_awaited_once_with(action)
        ss.evaluate_security_risk.assert_called_once_with(action)
        ss.apply_confirmation_state.assert_called_once()


# ── handle_pending_confirmation ──────────────────────────────────────


class TestHandlePendingConfirmation:
    @pytest.mark.asyncio
    async def test_returns_false_for_no_confirmation_attr(self):
        ctx = _make_context()
        svc = ConfirmationService(ctx, _make_safety_service())
        action = cast(Action, SimpleNamespace())  # no confirmation_state
        assert await svc.handle_pending_confirmation(action) is False

    @pytest.mark.asyncio
    async def test_returns_false_when_not_awaiting(self):
        ctx = _make_context()
        svc = ConfirmationService(ctx, _make_safety_service())
        action = cast(
            Action,
            SimpleNamespace(confirmation_state=ActionConfirmationStatus.CONFIRMED),
        )
        assert await svc.handle_pending_confirmation(action) is False

    @pytest.mark.asyncio
    async def test_transitions_when_awaiting(self):
        ctx = _make_context()
        svc = ConfirmationService(ctx, _make_safety_service())
        action = cast(
            Action,
            SimpleNamespace(
                confirmation_state=ActionConfirmationStatus.AWAITING_CONFIRMATION
            ),
        )
        result = await svc.handle_pending_confirmation(action)
        assert result is True
        ctx.set_agent_state.assert_awaited_once_with(
            AgentState.AWAITING_USER_CONFIRMATION
        )


# ── action_counts ────────────────────────────────────────────────────


class TestActionCounts:
    def test_initial_counts(self):
        svc = ConfirmationService(_make_context(), _make_safety_service())
        counts = svc.action_counts
        assert counts["replay_actions"] == 0
        assert counts["live_actions"] == 0
