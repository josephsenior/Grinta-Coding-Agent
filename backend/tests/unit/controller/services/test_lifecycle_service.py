"""Tests for LifecycleService."""

import unittest
from unittest.mock import MagicMock, patch

from backend.controller.services.lifecycle_service import LifecycleService


class TestLifecycleService(unittest.TestCase):
    """Test LifecycleService controller lifecycle management."""

    def setUp(self):
        """Create mock controller for testing."""
        self.mock_controller = MagicMock()
        self.service = LifecycleService(self.mock_controller)

    @patch("backend.controller.services.lifecycle_service.EventStreamSubscriber")
    def test_initialize_core_attributes(self, mock_subscriber_enum):
        """Test initialize_core_attributes sets all core attributes."""
        mock_event_stream = MagicMock()
        mock_event_stream.sid = "stream-123"
        mock_agent = MagicMock()
        mock_file_store = MagicMock()
        mock_conversation_stats = MagicMock()
        mock_status_callback = MagicMock()
        mock_security_analyzer = MagicMock()

        self.service.initialize_core_attributes(
            sid="session-456",
            event_stream=mock_event_stream,
            agent=mock_agent,
            user_id="user-789",
            file_store=mock_file_store,
            headless_mode=True,
            conversation_stats=mock_conversation_stats,
            status_callback=mock_status_callback,
            security_analyzer=mock_security_analyzer,
        )

        # Check current implementation-set attributes
        self.assertEqual(self.mock_controller.user_id, "user-789")
        self.assertEqual(self.mock_controller.file_store, mock_file_store)
        self.assertTrue(self.mock_controller.headless_mode)
        self.assertEqual(self.mock_controller.status_callback, mock_status_callback)
        self.assertEqual(self.mock_controller.security_analyzer, mock_security_analyzer)

        # Check event stream subscription
        mock_event_stream.subscribe.assert_called_once()

    @patch("backend.controller.services.lifecycle_service.EventStreamSubscriber")
    def test_initialize_core_attributes_sid_fallback(self, mock_subscriber_enum):
        """Test initialize_core_attributes uses event_stream.sid when sid is None."""
        mock_event_stream = MagicMock()
        mock_event_stream.sid = "fallback-sid"
        mock_agent = MagicMock()

        self.service.initialize_core_attributes(
            sid=None,
            event_stream=mock_event_stream,
            agent=mock_agent,
            user_id=None,
            file_store=None,
            headless_mode=False,
            conversation_stats=MagicMock(),
            status_callback=None,
            security_analyzer=MagicMock(),
        )

    @patch("backend.controller.services.lifecycle_service.EventStreamSubscriber")
    @patch("backend.core.enums.LifecyclePhase")
    def test_initialize_core_attributes_sets_lifecycle_phase(
        self, mock_lifecycle_phase, mock_subscriber_enum
    ):
        """Test initialize_core_attributes sets lifecycle to ACTIVE."""
        mock_event_stream = MagicMock()
        mock_event_stream.sid = "sid"

        self.service.initialize_core_attributes(
            sid="test",
            event_stream=mock_event_stream,
            agent=MagicMock(),
            user_id=None,
            file_store=None,
            headless_mode=False,
            conversation_stats=MagicMock(),
            status_callback=None,
            security_analyzer=MagicMock(),
        )

        self.assertEqual(self.mock_controller._lifecycle, mock_lifecycle_phase.ACTIVE)

    @patch("backend.controller.services.lifecycle_service.StateTracker")
    @patch("backend.controller.services.lifecycle_service.ReplayManager")
    def test_initialize_state_and_tracking(
        self, mock_replay_manager_class, mock_state_tracker_class
    ):
        """Test initialize_state_and_tracking creates StateTracker and ReplayManager."""
        mock_file_store = MagicMock()
        mock_conversation_stats = MagicMock()
        mock_initial_state = MagicMock()
        mock_replay_events = [MagicMock(), MagicMock()]

        mock_state_tracker = MagicMock()
        mock_state_tracker.state = MagicMock()
        mock_state_tracker_class.return_value = mock_state_tracker

        mock_replay_manager = MagicMock()
        mock_replay_manager_class.return_value = mock_replay_manager

        self.service.initialize_state_and_tracking(
            sid="session-123",
            file_store=mock_file_store,
            user_id="user-456",
            initial_state=mock_initial_state,
            conversation_stats=mock_conversation_stats,
            iteration_delta=100,
            budget_per_task_delta=50.0,
            confirmation_mode=True,
            replay_events=mock_replay_events,
        )

        # Check StateTracker created
        mock_state_tracker_class.assert_called_once_with(
            "session-123", mock_file_store, "user-456"
        )
        self.assertEqual(self.mock_controller.state_tracker, mock_state_tracker)

        # Check set_initial_state called
        self.mock_controller.set_initial_state.assert_called_once_with(
            state=mock_initial_state,
            conversation_stats=mock_conversation_stats,
            max_iterations=100,
            max_budget_per_task=50.0,
            confirmation_mode=True,
        )

        # Check confirmation_mode set
        self.assertTrue(self.mock_controller.confirmation_mode)

        # Check ReplayManager created
        mock_replay_manager_class.assert_called_once_with(mock_replay_events)
        self.assertEqual(self.mock_controller._replay_manager, mock_replay_manager)

    @patch("backend.controller.services.lifecycle_service.StateTracker")
    @patch("backend.controller.services.lifecycle_service.ReplayManager")
    def test_initialize_state_and_tracking_none_values(
        self, mock_replay_manager_class, mock_state_tracker_class
    ):
        """Test initialize_state_and_tracking handles None values."""
        mock_state_tracker = MagicMock()
        mock_state_tracker.state = MagicMock()
        mock_state_tracker_class.return_value = mock_state_tracker

        self.service.initialize_state_and_tracking(
            sid=None,
            file_store=None,
            user_id=None,
            initial_state=None,
            conversation_stats=MagicMock(),
            iteration_delta=0,
            budget_per_task_delta=None,
            confirmation_mode=False,
            replay_events=None,
        )

        # Should create StateTracker with None values
        mock_state_tracker_class.assert_called_once_with(None, None, None)

        # Should create ReplayManager with None
        mock_replay_manager_class.assert_called_once_with(None)

        # Confirmation mode should be False
        self.assertFalse(self.mock_controller.confirmation_mode)

    def test_initialize_agent_configs_with_configs(self):
        """Test initialize_agent_configs stores config dictionaries."""
        mock_agent_to_llm_config = {
            "agent1": MagicMock(),
            "agent2": MagicMock(),
        }
        mock_agent_configs = {
            "agent1": MagicMock(),
            "agent2": MagicMock(),
        }

        self.service.initialize_agent_configs(
            agent_to_llm_config=mock_agent_to_llm_config,
            agent_configs=mock_agent_configs,
            iteration_delta=50,
            budget_per_task_delta=25.0,
        )

        self.assertEqual(
            self.mock_controller.agent_to_llm_config, mock_agent_to_llm_config
        )
        self.assertEqual(self.mock_controller.agent_configs, mock_agent_configs)
        self.assertEqual(self.mock_controller._initial_max_iterations, 50)
        self.assertEqual(self.mock_controller._initial_max_budget_per_task, 25.0)

    def test_initialize_agent_configs_none_configs(self):
        """Test initialize_agent_configs handles None config dictionaries."""
        self.service.initialize_agent_configs(
            agent_to_llm_config=None,
            agent_configs=None,
            iteration_delta=10,
            budget_per_task_delta=None,
        )

        # Should default to empty dictionaries
        self.assertEqual(self.mock_controller.agent_to_llm_config, {})
        self.assertEqual(self.mock_controller.agent_configs, {})
        self.assertEqual(self.mock_controller._initial_max_iterations, 10)
        self.assertIsNone(self.mock_controller._initial_max_budget_per_task)

    def test_initialize_agent_configs_empty_configs(self):
        """Test initialize_agent_configs stores empty config dictionaries."""
        self.service.initialize_agent_configs(
            agent_to_llm_config={},
            agent_configs={},
            iteration_delta=0,
            budget_per_task_delta=0.0,
        )

        self.assertEqual(self.mock_controller.agent_to_llm_config, {})
        self.assertEqual(self.mock_controller.agent_configs, {})
        self.assertEqual(self.mock_controller._initial_max_iterations, 0)
        self.assertEqual(self.mock_controller._initial_max_budget_per_task, 0.0)

    @patch("backend.controller.services.lifecycle_service.EventStreamSubscriber")
    def test_full_initialization_workflow(self, mock_subscriber_enum):
        """Test complete initialization workflow using all three methods."""
        # Step 1: Initialize core attributes
        mock_event_stream = MagicMock()
        mock_event_stream.sid = "sid"
        mock_agent = MagicMock()

        self.service.initialize_core_attributes(
            sid="session-1",
            event_stream=mock_event_stream,
            agent=mock_agent,
            user_id="user-1",
            file_store=MagicMock(),
            headless_mode=False,
            conversation_stats=MagicMock(),
            status_callback=MagicMock(),
            security_analyzer=MagicMock(),
        )

        # Step 2: Initialize state and tracking
        with patch("backend.controller.services.lifecycle_service.StateTracker"):
            with patch("backend.controller.services.lifecycle_service.ReplayManager"):
                self.service.initialize_state_and_tracking(
                    sid="session-1",
                    file_store=MagicMock(),
                    user_id="user-1",
                    initial_state=MagicMock(),
                    conversation_stats=MagicMock(),
                    iteration_delta=100,
                    budget_per_task_delta=50.0,
                    confirmation_mode=True,
                    replay_events=[],
                )

        # Step 3: Initialize agent configs
        self.service.initialize_agent_configs(
            agent_to_llm_config={"agent": MagicMock()},
            agent_configs={"agent": MagicMock()},
            iteration_delta=100,
            budget_per_task_delta=50.0,
        )

        # Verify controller is fully initialized
        self.assertIsNotNone(self.mock_controller.state_tracker)
        self.assertIsNotNone(self.mock_controller._replay_manager)
        self.assertIsNotNone(self.mock_controller.agent_to_llm_config)


if __name__ == "__main__":
    unittest.main()
