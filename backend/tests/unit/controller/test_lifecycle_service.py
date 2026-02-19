"""Unit tests for backend.controller.services.lifecycle_service — LifecycleService."""

from __future__ import annotations

from unittest.mock import MagicMock, patch


from backend.controller.services.lifecycle_service import LifecycleService
from backend.events import EventStreamSubscriber


# ── Helpers ──────────────────────────────────────────────────────────


def _make_controller() -> MagicMock:
    ctrl = MagicMock()
    ctrl.id = None
    ctrl.user_id = None
    ctrl.file_store = None
    ctrl.agent = None
    ctrl.headless_mode = False
    ctrl.event_stream = None
    ctrl.status_callback = None
    ctrl.security_analyzer = None
    ctrl.conversation_stats = None
    ctrl.state_tracker = None
    ctrl.state = None
    ctrl.confirmation_mode = False
    ctrl.agent_to_llm_config = {}
    ctrl.agent_configs = {}
    ctrl._initial_max_iterations = 0
    ctrl._initial_max_budget_per_task = None
    ctrl._replay_manager = None
    ctrl._lifecycle = None
    return ctrl


# ── initialize_core_attributes ───────────────────────────────────────


class TestInitializeCoreAttributes:
    def test_wires_all_attributes(self):
        ctrl = _make_controller()
        svc = LifecycleService(ctrl)

        event_stream = MagicMock()
        event_stream.sid = "stream-sid"
        agent = MagicMock()
        file_store = MagicMock()
        stats = MagicMock()
        status_cb = MagicMock()
        security = MagicMock()

        svc.initialize_core_attributes(
            sid="s1",
            event_stream=event_stream,
            agent=agent,
            user_id="u1",
            file_store=file_store,
            headless_mode=True,
            conversation_stats=stats,
            status_callback=status_cb,
            security_analyzer=security,
        )

        assert ctrl.id == "s1"
        assert ctrl.user_id == "u1"
        assert ctrl.file_store is file_store
        assert ctrl.agent is agent
        assert ctrl.headless_mode is True
        assert ctrl.conversation_stats is stats
        assert ctrl.event_stream is event_stream
        assert ctrl.status_callback is status_cb
        assert ctrl.security_analyzer is security

        from backend.core.enums import LifecyclePhase

        assert ctrl._lifecycle == LifecyclePhase.ACTIVE

    def test_falls_back_to_event_stream_sid(self):
        ctrl = _make_controller()
        svc = LifecycleService(ctrl)

        event_stream = MagicMock()
        event_stream.sid = "fallback-sid"

        svc.initialize_core_attributes(
            sid=None,
            event_stream=event_stream,
            agent=MagicMock(),
            user_id=None,
            file_store=None,
            headless_mode=False,
            conversation_stats=MagicMock(),
            status_callback=None,
            security_analyzer=None,
        )

        assert ctrl.id == "fallback-sid"

    def test_subscribes_to_event_stream(self):
        ctrl = _make_controller()
        svc = LifecycleService(ctrl)

        event_stream = MagicMock()
        event_stream.sid = "s1"

        svc.initialize_core_attributes(
            sid="s1",
            event_stream=event_stream,
            agent=MagicMock(),
            user_id=None,
            file_store=None,
            headless_mode=False,
            conversation_stats=MagicMock(),
            status_callback=None,
            security_analyzer=None,
        )

        event_stream.subscribe.assert_called_once_with(
            EventStreamSubscriber.AGENT_CONTROLLER, ctrl.on_event, "s1"
        )


# ── initialize_state_and_tracking ────────────────────────────────────


class TestInitializeStateAndTracking:
    def test_creates_state_tracker(self):
        ctrl = _make_controller()
        svc = LifecycleService(ctrl)

        file_store = MagicMock()

        with patch(
            "backend.controller.services.lifecycle_service.StateTracker"
        ) as mock_st:
            svc.initialize_state_and_tracking(
                sid="s1",
                file_store=file_store,
                user_id="u1",
                initial_state=MagicMock(),
                conversation_stats=MagicMock(),
                iteration_delta=100,
                budget_per_task_delta=5.0,
                confirmation_mode=True,
                replay_events=None,
            )

            mock_st.assert_called_once_with("s1", file_store, "u1")
            assert ctrl.state_tracker == mock_st.return_value
            assert ctrl.confirmation_mode is True
            assert ctrl.state == mock_st.return_value.state
            ctrl.set_initial_state.assert_called_once()

    def test_sets_replay_manager(self):
        ctrl = _make_controller()
        svc = LifecycleService(ctrl)

        replay_events = [MagicMock(), MagicMock()]

        with patch("backend.controller.services.lifecycle_service.StateTracker"):
            with patch(
                "backend.controller.services.lifecycle_service.ReplayManager"
            ) as mock_rm:
                svc.initialize_state_and_tracking(
                    sid="s1",
                    file_store=None,
                    user_id=None,
                    initial_state=None,
                    conversation_stats=MagicMock(),
                    iteration_delta=50,
                    budget_per_task_delta=None,
                    confirmation_mode=False,
                    replay_events=replay_events,
                )

                mock_rm.assert_called_once_with(replay_events)
                assert ctrl._replay_manager == mock_rm.return_value


# ── initialize_agent_configs ─────────────────────────────────────────


class TestInitializeAgentConfigs:
    def test_stores_configs(self):
        ctrl = _make_controller()
        svc = LifecycleService(ctrl)

        llm_configs = {"agent1": MagicMock()}
        agent_configs = {"agent1": MagicMock()}

        svc.initialize_agent_configs(
            agent_to_llm_config=llm_configs,
            agent_configs=agent_configs,
            iteration_delta=200,
            budget_per_task_delta=10.0,
        )

        assert ctrl.agent_to_llm_config == llm_configs
        assert ctrl.agent_configs == agent_configs
        assert ctrl._initial_max_iterations == 200
        assert ctrl._initial_max_budget_per_task == 10.0

    def test_defaults_none_to_empty_dict(self):
        ctrl = _make_controller()
        svc = LifecycleService(ctrl)

        svc.initialize_agent_configs(
            agent_to_llm_config=None,
            agent_configs=None,
            iteration_delta=50,
            budget_per_task_delta=None,
        )

        assert ctrl.agent_to_llm_config == {}
        assert ctrl.agent_configs == {}
        assert ctrl._initial_max_iterations == 50
        assert ctrl._initial_max_budget_per_task is None
