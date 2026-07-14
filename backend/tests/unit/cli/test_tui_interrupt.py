from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest

from backend.cli.tui.screen.messages import ScreenMessagesMixin
from backend.core.enums import AgentState


@pytest.mark.asyncio
async def test_interrupt_stops_controller_before_releasing_agent_poller(
    monkeypatch,
) -> None:
    stop_requested = asyncio.Event()
    order: list[str] = []

    async def poller() -> None:
        try:
            await stop_requested.wait()
            order.append('poller-stopped')
        except asyncio.CancelledError:
            order.append('poller-cancelled')
            raise

    class Controller:
        state = AgentState.RUNNING

        def mark_user_interrupt_stop(self) -> None:
            order.append('marked')

        async def stop(self) -> None:
            order.append('controller-stop')
            self.state = AgentState.STOPPED
            stop_requested.set()

        def get_agent_state(self) -> AgentState:
            return self.state

        async def set_agent_state_to(self, state: AgentState) -> None:
            self.state = state

    class Screen(ScreenMessagesMixin):
        def __init__(self) -> None:
            self._controller = Controller()
            self._agent_task = asyncio.create_task(poller())
            self._interrupt_task = None
            self._hud = MagicMock()

        def finalize_thinking(self) -> None:
            pass

        def query_one(self, *args, **kwargs):
            return MagicMock()

        def _finalize_turn_duration(self) -> None:
            pass

        def _render_hud_bar(self) -> None:
            pass

    monkeypatch.setattr(
        'backend.core.logging.logger.finalize_session_logging_audit',
        MagicMock(),
    )
    screen = Screen()

    screen._interrupt_agent()
    interrupt_task = screen._interrupt_task
    assert interrupt_task is not None
    await interrupt_task

    assert order == ['marked', 'controller-stop', 'poller-stopped']
    assert screen._controller.get_agent_state() == AgentState.STOPPED
    screen._hud.update_agent_state.assert_any_call('Stopping')
    screen._hud.update_agent_state.assert_any_call('Ready')
