"""Tests for ConfirmationService."""

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from backend.ledger.action import ActionConfirmationStatus
from backend.orchestration.services.confirmation_service import ConfirmationService


class TestConfirmationService(unittest.IsolatedAsyncioTestCase):
    """Test ConfirmationService action sourcing and confirmation logic."""

    def setUp(self):
        """Create mock context and dependencies for testing."""
        self.mock_controller = MagicMock()
        self.mock_controller._replay_manager = MagicMock()
        self.mock_controller.agent = MagicMock()
        self.mock_controller.state = MagicMock()
        self.mock_controller.state.confirmation_mode = False
        self.mock_controller.log = MagicMock()

        self.mock_context = MagicMock()
        self.mock_context.get_controller.return_value = self.mock_controller
        self.mock_context.set_agent_state = AsyncMock()

        self.mock_safety_service = MagicMock()
        self.mock_safety_service.action_requires_confirmation = MagicMock(
            return_value=False
        )
        self.mock_safety_service.analyze_security = AsyncMock()
        self.mock_safety_service.evaluate_security_risk = MagicMock(
            return_value=(False, False)
        )
        self.mock_safety_service.apply_confirmation_state = MagicMock()

        self.service = ConfirmationService(self.mock_context, self.mock_safety_service)

    def test_initialization(self):
        """Test service initializes with zero action counts."""
        self.assertEqual(self.service._context, self.mock_context)
        self.assertEqual(self.service._safety_service, self.mock_safety_service)
        self.assertEqual(self.service._replay_action_count, 0)
        self.assertEqual(self.service._live_action_count, 0)

    def test_get_next_action_from_replay(self):
        """Test get_next_action returns action from replay manager."""
        self.mock_controller._replay_manager.should_replay.return_value = True
        mock_action = MagicMock()
        mock_action.id = 'action-123'
        self.mock_controller._replay_manager.step.return_value = mock_action
        self.mock_controller._replay_manager.replay_index = 5

        action = self.service.get_next_action()

        self.assertEqual(action, mock_action)
        self.assertEqual(self.service._replay_action_count, 1)
        self.mock_controller.log.assert_called_once()

    def test_get_next_action_from_agent(self):
        """Test get_next_action returns action from agent when not replaying."""
        from backend.ledger import EventSource

        self.mock_controller._replay_manager.should_replay.return_value = False
        mock_action = MagicMock()
        self.mock_controller.agent.step.return_value = mock_action

        action = self.service.get_next_action()

        self.assertEqual(action, mock_action)
        self.assertEqual(action.source, EventSource.AGENT)
        self.assertEqual(self.service._live_action_count, 1)
        self.mock_controller.agent.step.assert_called_once_with(
            self.mock_controller.state
        )

    def test_get_next_action_mixed_replay_and_live(self):
        """Test get_next_action tracks both replay and live actions correctly."""
        self.mock_controller._replay_manager.should_replay.side_effect = [
            True,
            True,
            False,
            False,
        ]
        mock_replay_action = MagicMock()
        mock_replay_action.id = 'replay-1'
        mock_live_action = MagicMock()

        self.mock_controller._replay_manager.step.return_value = mock_replay_action
        self.mock_controller.agent.step.return_value = mock_live_action

        # Two replay actions
        self.service.get_next_action()
        self.service.get_next_action()

        # Two live actions
        self.service.get_next_action()
        self.service.get_next_action()

        self.assertEqual(self.service._replay_action_count, 2)
        self.assertEqual(self.service._live_action_count, 2)

    def test_is_replay_mode_true(self):
        """Test is_replay_mode returns True when in replay mode."""
        self.mock_controller._replay_manager.replay_mode = True

        self.assertTrue(self.service.is_replay_mode)

    def test_is_replay_mode_false(self):
        """Test is_replay_mode returns False when not in replay mode."""
        self.mock_controller._replay_manager.replay_mode = False

        self.assertFalse(self.service.is_replay_mode)

    def test_replay_progress_in_replay_mode(self):
        """Test replay_progress returns (index, total) in replay mode."""
        self.mock_controller._replay_manager.replay_mode = True
        self.mock_controller._replay_manager.replay_index = 5
        self.mock_controller._replay_manager.replay_events = [
            'e1',
            'e2',
            'e3',
            'e4',
            'e5',
            'e6',
            'e7',
        ]

        progress = self.service.replay_progress

        self.assertEqual(progress, (5, 7))

    def test_replay_progress_not_in_replay_mode(self):
        """Test replay_progress returns None when not in replay mode."""
        self.mock_controller._replay_manager.replay_mode = False

        progress = self.service.replay_progress

        self.assertIsNone(progress)

    def test_replay_progress_with_no_events(self):
        """Test replay_progress handles None replay_events."""
        self.mock_controller._replay_manager.replay_mode = True
        self.mock_controller._replay_manager.replay_index = 0
        self.mock_controller._replay_manager.replay_events = None

        progress = self.service.replay_progress

        self.assertEqual(progress, (0, 0))

    def test_action_counts(self):
        """Test action_counts returns counts dictionary."""
        self.service._replay_action_count = 5
        self.service._live_action_count = 3

        counts = self.service.action_counts

        self.assertEqual(
            counts,
            {
                'replay_actions': 5,
                'live_actions': 3,
            },
        )

    async def test_evaluate_action_confirmation_mode_off(self):
        """Test evaluate_action does nothing when confirmation_mode is off."""
        self.mock_controller.state.confirmation_mode = False
        mock_action = MagicMock()

        await self.service.evaluate_action(mock_action)

        # Should not call safety service methods
        self.mock_safety_service.action_requires_confirmation.assert_not_called()
        self.mock_safety_service.analyze_security.assert_not_called()

    async def test_evaluate_action_no_confirmation_required(self):
        """Test evaluate_action skips analysis when action doesn't require confirmation."""
        self.mock_controller.state.confirmation_mode = True
        self.mock_safety_service.action_requires_confirmation.return_value = False
        mock_action = MagicMock()

        await self.service.evaluate_action(mock_action)

        self.mock_safety_service.action_requires_confirmation.assert_called_once_with(
            mock_action
        )
        self.mock_safety_service.analyze_security.assert_not_called()

    async def test_evaluate_action_with_confirmation_required(self):
        """Test evaluate_action performs full security analysis."""
        self.mock_controller.state.confirmation_mode = True
        self.mock_safety_service.action_requires_confirmation.return_value = True
        self.mock_safety_service.evaluate_security_risk.return_value = (True, False)

        mock_action = MagicMock()

        await self.service.evaluate_action(mock_action)

        # Should call all security methods in order
        self.mock_safety_service.action_requires_confirmation.assert_called_once_with(
            mock_action
        )
        self.mock_safety_service.analyze_security.assert_called_once_with(mock_action)
        self.mock_safety_service.evaluate_security_risk.assert_called_once_with(
            mock_action
        )
        self.mock_safety_service.apply_confirmation_state.assert_called_once_with(
            mock_action,
            is_high_security_risk=True,
            is_ask_for_every_action=False,
        )

    async def test_evaluate_action_high_risk_and_ask_every_action(self):
        """Test evaluate_action with both high risk and ask every action flags."""
        self.mock_controller.state.confirmation_mode = True
        self.mock_safety_service.action_requires_confirmation.return_value = True
        self.mock_safety_service.evaluate_security_risk.return_value = (True, True)

        mock_action = MagicMock()

        await self.service.evaluate_action(mock_action)

        self.mock_safety_service.apply_confirmation_state.assert_called_once_with(
            mock_action,
            is_high_security_risk=True,
            is_ask_for_every_action=True,
        )

    async def test_handle_pending_confirmation_no_confirmation_state(self):
        """Test handle_pending_confirmation returns False when no confirmation_state."""
        mock_action = MagicMock(spec=[])  # No confirmation_state attribute

        result = await self.service.handle_pending_confirmation(mock_action)

        self.assertFalse(result)
        self.mock_context.set_agent_state.assert_not_called()

    async def test_handle_pending_confirmation_not_awaiting(self):
        """Test handle_pending_confirmation returns False when not awaiting confirmation."""
        mock_action = MagicMock()
        mock_action.confirmation_state = ActionConfirmationStatus.CONFIRMED

        result = await self.service.handle_pending_confirmation(mock_action)

        self.assertFalse(result)
        self.mock_context.set_agent_state.assert_not_called()

    async def test_handle_pending_confirmation_awaiting(self):
        """Test handle_pending_confirmation transitions state when awaiting confirmation."""
        from backend.core.schemas import AgentState

        mock_action = MagicMock()
        mock_action.confirmation_state = ActionConfirmationStatus.AWAITING_CONFIRMATION

        result = await self.service.handle_pending_confirmation(mock_action)

        self.assertTrue(result)
        self.mock_context.set_agent_state.assert_called_once_with(
            AgentState.AWAITING_USER_CONFIRMATION
        )

    async def test_handle_observation_for_pending_action(self):
        """Test handle_observation_for_pending_action delegates to transition logic."""
        mock_observation = MagicMock()
        mock_ctx = MagicMock()

        with patch(
            'backend.orchestration.services.observation_service.transition_agent_state_logic',
            new_callable=AsyncMock,
        ) as mock_transition:
            await self.service.handle_observation_for_pending_action(
                mock_observation, mock_ctx
            )

            mock_transition.assert_called_once_with(
                self.mock_controller,
                mock_ctx,
                mock_observation,
            )

    async def test_handle_observation_for_pending_action_none_ctx(self):
        """Test handle_observation_for_pending_action handles None ctx."""
        mock_observation = MagicMock()

        with patch(
            'backend.orchestration.services.observation_service.transition_agent_state_logic',
            new_callable=AsyncMock,
        ) as mock_transition:
            await self.service.handle_observation_for_pending_action(
                mock_observation, None
            )

            mock_transition.assert_called_once_with(
                self.mock_controller,
                None,
                mock_observation,
            )

    def test_get_next_action_logs_action_type(self):
        """Test get_next_action logs action type in extra metadata."""
        self.mock_controller._replay_manager.should_replay.return_value = False
        mock_action = MagicMock()
        mock_action.__class__.__name__ = 'TestAction'
        self.mock_controller.agent.step.return_value = mock_action

        self.service.get_next_action()

        # Check log was called with action_type in extra
        call_kwargs = self.mock_controller.log.call_args[1]
        self.assertEqual(call_kwargs['extra']['action_type'], 'TestAction')
        self.assertEqual(call_kwargs['extra']['msg_type'], 'LIVE_ACTION')


if __name__ == '__main__':
    unittest.main()
