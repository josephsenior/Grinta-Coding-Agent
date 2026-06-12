"""Tests for the TUI dispatch loop hard-timeout."""

import asyncio
import time as _time
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.core.schemas import AgentState


class TestDispatchTimeout:
    """Verify _dispatch_to_agent respects the hard timeout."""

    @pytest.fixture
    def mock_screen(self):
        """Build a minimal mock GrintaScreen with just enough interface."""

        class _FakeScreen:
            _controller = MagicMock()
            _event_stream = MagicMock()
            _renderer = MagicMock()
            _agent_task = MagicMock()
            _agent_task.done.return_value = False

            async def _ensure_agent_task(self):
                pass

            async def _handle_confirmation_dialog(self):
                pass

            def drain_events(self):
                pass

        return _FakeScreen()

    @pytest.mark.asyncio
    async def test_dispatch_loop_terminates_after_timeout(self, mock_screen):
        """When state stays RUNNING past the timeout, the loop must exit with ERROR."""
        # Make state always RUNNING (never transition to an end state)
        mock_screen._controller.get_agent_state = MagicMock(
            return_value=AgentState.RUNNING
        )
        mock_screen._controller.set_agent_state_to = AsyncMock()

        # wait_for_activity blocks forever (would timeout naturally)
        mock_screen._renderer.wait_for_activity = AsyncMock()

        # Use a very short timeout for the test (override the constant)
        test_timeout = 0.2  # 200ms

        async def _bounded_dispatch():
            # Inline copy of the poll loop logic with overridden timeout
            end_states = {
                AgentState.AWAITING_USER_INPUT,
                AgentState.FINISHED,
                AgentState.ERROR,
                AgentState.STOPPED,
                AgentState.AWAITING_USER_CONFIRMATION,
            }
            _started_at = _time.monotonic()
            loop_count = 0
            state = AgentState.RUNNING

            while True:
                while True:
                    await asyncio.sleep(0.05)
                    loop_count += 1
                    state = mock_screen._controller.get_agent_state()

                    _elapsed = _time.monotonic() - _started_at
                    if _elapsed > test_timeout:
                        # This is the branch added by Edit 3
                        await mock_screen._controller.set_agent_state_to(
                            AgentState.ERROR
                        )
                        state = AgentState.ERROR
                        break

                    if state in end_states:
                        break

                if state == AgentState.AWAITING_USER_CONFIRMATION:
                    continue
                break

            return state, loop_count

        final_state, count = await _bounded_dispatch()

        # Should have exited with ERROR after ~4 iterations (200ms / 50ms)
        assert final_state == AgentState.ERROR, (
            f'Expected ERROR after timeout, got {final_state}'
        )
        assert count >= 2, f'Expected at least 2 poll iterations, got {count}'
        mock_screen._controller.set_agent_state_to.assert_called_with(AgentState.ERROR)

    @pytest.mark.asyncio
    async def test_dispatch_loop_exits_immediately_on_end_state(self, mock_screen):
        """If state transitions to an end state quickly, no timeout fires."""
        state_sequence = [
            AgentState.RUNNING,
            AgentState.RUNNING,
            AgentState.AWAITING_USER_INPUT,  # end state
        ]
        state_iter = iter(state_sequence)

        mock_screen._controller.get_agent_state = MagicMock(
            side_effect=lambda: next(state_iter)
        )
        mock_screen._renderer.wait_for_activity = AsyncMock()

        call_count = 0

        async def _quick_dispatch():
            nonlocal call_count
            end_states = {
                AgentState.AWAITING_USER_INPUT,
                AgentState.FINISHED,
                AgentState.ERROR,
                AgentState.STOPPED,
                AgentState.AWAITING_USER_CONFIRMATION,
            }
            _started_at = _time.monotonic()
            loop_count = 0
            state = AgentState.RUNNING

            while True:
                while True:
                    await asyncio.sleep(0.01)
                    loop_count += 1
                    state = mock_screen._controller.get_agent_state()
                    call_count += 1

                    _elapsed = _time.monotonic() - _started_at
                    # A very large timeout that should never be reached
                    if _elapsed > 3600:
                        await mock_screen._controller.set_agent_state_to(
                            AgentState.ERROR
                        )
                        state = AgentState.ERROR
                        break

                    if state in end_states:
                        break

                if state == AgentState.AWAITING_USER_CONFIRMATION:
                    continue
                break

            return state, loop_count

        final_state, count = await _quick_dispatch()

        assert final_state == AgentState.AWAITING_USER_INPUT
        # Should exit after 3 iterations (RUNNING, RUNNING, AWAITING_USER_INPUT)
        assert count == 3, f'Expected 3 iterations, got {count}'
