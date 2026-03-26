"""Unit tests for backend.api.session.agent_session."""

from __future__ import annotations

import time
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from backend.api.session.agent_session import AgentSession, StartupContext
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

    async def test_start_restored_session_uses_resume_state_once(self):
        session = self._make_session()
        session.sid = "sid-1"
        session.user_id = "user-1"
        session.runtime = None
        session.memory = None
        session.llm_registry = MagicMock()
        session.conversation_stats = MagicMock()
        session._status_callback = None
        session._starting = False
        session._startup_failed = False
        session._started_at = 0
        session._init_ready = MagicMock()
        session.config = None
        session._selected_repository = None
        session._selected_branch = None

        controller = MagicMock()
        controller.state = MagicMock()
        controller.state.resume_state = AgentState.PAUSED
        session.controller = None

        config = MagicMock()
        agent = MagicMock()

        async def setup_controller(*args, **kwargs):
            session.controller = controller
            return None, True

        with (
            patch.object(session, "_handle_auth_phase", new=AsyncMock()),
            patch.object(session, "_setup_runtime_and_providers", new=AsyncMock(return_value=True)),
            patch.object(session, "_setup_memory_and_mcp_tools", new=AsyncMock()),
            patch.object(
                session,
                "_setup_controller_and_handle_replay",
                new=AsyncMock(side_effect=setup_controller),
            ) as mock_setup_controller,
            patch.object(session, "_handle_plugin_phase", new=AsyncMock()),
            patch.object(session, "_start_agent_execution", wraps=session._start_agent_execution) as mock_start_execution,
        ):
            await session.start(
                runtime_name="local",
                config=config,
                agent=agent,
                max_iterations=10,
                agent_to_llm_config=None,
                agent_configs=None,
            )

        mock_setup_controller.assert_awaited_once()
        mock_start_execution.assert_called_once_with(None)
        emitted = session.event_stream.add_event.call_args_list[-1].args[0]
        self.assertEqual(emitted.agent_state, AgentState.PAUSED)
        session._init_ready.set.assert_called()

    def test_build_startup_log_metadata_includes_parse_telemetry(self):
        session = self._make_session()
        ctx = StartupContext(started_at=time.time() - 0.01, restored_state=True)

        with patch(
            "backend.api.session.agent_session.get_fn_call_parse_telemetry_counters",
            return_value={
                "strict_parse_success": 3,
                "strict_parse_failure": 1,
                "malformed_payload_rejection": 2,
            },
        ):
            metadata = session._build_startup_log_metadata(ctx, success=True)

        self.assertEqual(metadata["signal"], "agent_session_start")
        self.assertTrue(metadata["success"])
        self.assertEqual(
            metadata["strict_parse_telemetry"],
            {
                "strict_parse_success": 3,
                "strict_parse_failure": 1,
                "malformed_payload_rejection": 2,
            },
        )
