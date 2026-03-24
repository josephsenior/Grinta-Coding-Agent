"""Unit tests for backend.api.session.agent_session."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from backend.api.session.agent_session import AgentSession
from backend.core.schemas import AgentState
from backend.events.action import MessageAction


class TestAgentSessionStartup(unittest.IsolatedAsyncioTestCase):
    def _make_session(self) -> AgentSession:
        session = AgentSession.__new__(AgentSession)
        session._closed = False
        session.event_stream = MagicMock()
        session.logger = MagicMock()
        session.controller = MagicMock()
        session.controller.state = MagicMock()
        session.controller.state.resume_state = None
        return session

    def test_start_agent_execution_defaults_to_awaiting_user_input(self):
        session = self._make_session()

        session._start_agent_execution(None)

        emitted = session.event_stream.add_event.call_args_list[-1].args[0]
        self.assertEqual(emitted.agent_state, AgentState.AWAITING_USER_INPUT)

    def test_start_agent_execution_uses_resume_state_when_restored(self):
        session = self._make_session()
        session.controller.state.resume_state = AgentState.PAUSED

        session._start_agent_execution(None)

        emitted = session.event_stream.add_event.call_args_list[-1].args[0]
        self.assertEqual(emitted.agent_state, AgentState.PAUSED)

    def test_initial_message_still_forces_running_state(self):
        session = self._make_session()
        session.controller.state.resume_state = AgentState.PAUSED
        initial_message = MessageAction(content="continue")

        session._start_agent_execution(initial_message)

        self.assertEqual(session.event_stream.add_event.call_args_list[0].args[0], initial_message)
        emitted = session.event_stream.add_event.call_args_list[-1].args[0]
        self.assertEqual(emitted.agent_state, AgentState.RUNNING)

    async def test_setup_controller_returns_restored_state_flag(self):
        session = self._make_session()
        session._run_replay = MagicMock()
        session._create_controller = MagicMock(return_value=(MagicMock(), True))

        config = MagicMock()
        config.security.confirmation_mode = False

        initial_message, restored = await session._setup_controller_and_handle_replay(
            replay_json=None,
            initial_message=None,
            agent=MagicMock(),
            config=config,
            max_iterations=10,
            max_budget_per_task=None,
            agent_to_llm_config=None,
            agent_configs=None,
            user_settings=None,
        )

        self.assertIsNone(initial_message)
        self.assertTrue(restored)
        self.assertIsNotNone(session.controller)
