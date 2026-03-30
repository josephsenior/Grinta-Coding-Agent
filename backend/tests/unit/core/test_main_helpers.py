"""Tests for backend.core.bootstrap.main — entry point helpers."""

from __future__ import annotations

from typing import Any, cast
from unittest.mock import MagicMock, patch, AsyncMock

import pytest

from backend.core.config.app_config import AppConfig
from backend.core.bootstrap.main import (
    _validate_run_controller_inputs,
    _setup_replay_events,
    _validate_initial_action,
    _setup_initial_events,
    _prepare_final_state,
    _initialize_session_components,
    auto_continue_response,
    _setup_memory_and_mcp,
    _create_early_status_callback,
    _create_event_handler,
    _save_trajectory,
    load_replay_log,
    run_controller,
    _run_agent_loop,
    _setup_runtime_for_controller,
    _execute_controller_lifecycle,
)
from backend.ledger.action import MessageAction, NullAction
from backend.ledger.observation import AgentStateChangedObservation
from backend.core.enums import AgentState, RuntimeStatus


def test_validate_run_controller_inputs():
    config = MagicMock(spec=AppConfig)
    action = MessageAction(content="test")

    cfg, act = _validate_run_controller_inputs(config, action)
    assert cfg is config
    assert act is action

    with pytest.raises(TypeError):
        _validate_run_controller_inputs(None, action)

    with pytest.raises(TypeError):
        _validate_run_controller_inputs(config, None)


def test_setup_replay_events_none():
    config = MagicMock(spec=AppConfig)
    config.replay_transcript_path = None
    action = MessageAction(content="test")

    events, act = _setup_replay_events(config, action)
    assert events is None
    assert act is action


@patch("backend.core.bootstrap.main.load_replay_log")
def test_setup_replay_events_enabled(mock_load):
    config = MagicMock(spec=AppConfig)
    config.replay_transcript_path = "path.json"
    action = NullAction()

    mock_load.return_value = ([], action)
    events, act = _setup_replay_events(config, action)
    assert events == []
    assert act is action


def test_validate_initial_action():
    _validate_initial_action(MessageAction(content="hi"))
    _validate_initial_action(NullAction())

    with pytest.raises(AssertionError):
        bad_mock = MagicMock(spec=[])
        del bad_mock.content
        del bad_mock.message
        _validate_initial_action(bad_mock)


@patch("asyncio.get_running_loop")
def test_setup_initial_events(mock_get_loop):
    event_stream = MagicMock()
    action = MessageAction(content="hi")

    # No loop
    mock_get_loop.side_effect = RuntimeError()
    _setup_initial_events(event_stream, action, None)
    event_stream.add_event.assert_called_with(action, "user")

    # With state error
    initial_state = MagicMock()
    initial_state.last_error = "error"
    _setup_initial_events(event_stream, action, initial_state)
    # Checks that a recovery message was added
    event_stream.add_event.assert_called()


def test_prepare_final_state():
    mock_controller = MagicMock()
    # Explicitly set these to False to avoid truthy MagicMocks
    mock_controller._force_iteration_reset = False

    mock_state = MagicMock()
    mock_state._force_iteration_reset = False
    mock_state.iteration_flag.current_value = 10
    mock_controller.get_state.return_value = mock_state

    # Normal case
    res = _prepare_final_state(mock_controller)
    assert res is mock_state
    assert res.iteration_flag.current_value == 10

    # Forced reset case
    mock_controller._force_iteration_reset = True
    res = _prepare_final_state(mock_controller)
    assert res.iteration_flag.current_value == 0


@patch("backend.core.bootstrap.main.create_registry_and_conversation_stats")
@patch("backend.core.bootstrap.main.create_agent")
def test_initialize_session_components(mock_create_agent, mock_registry):
    config = AppConfig()
    mock_registry.return_value = (MagicMock(), MagicMock(), config)
    mock_create_agent.return_value = MagicMock()

    sid, llm, stats, cfg, agent = _initialize_session_components(config, "sid")
    assert sid == "sid"
    assert cfg is config


def test_auto_continue_response():
    resp = auto_continue_response(MagicMock())
    assert "continue" in resp
    assert "NEVER ASK" in resp


@patch("backend.core.bootstrap.main.create_memory")
@patch("backend.core.bootstrap.main.add_mcp_tools_to_agent")
@pytest.mark.asyncio
async def test_setup_memory_and_mcp_with_mcp(mock_add_mcp, mock_create_mem):
    config = AppConfig()
    config.mcp_host = "localhost"
    mock_runtime = MagicMock()
    mock_runtime.event_stream = MagicMock()
    mock_runtime.config.mcp.servers = []
    mock_agent = MagicMock()
    mock_agent.config.enable_mcp = True

    await _setup_memory_and_mcp(
        config, mock_runtime, "sid", None, None, None, mock_agent
    )

    mock_create_mem.assert_called()
    mock_add_mcp.assert_called()


def test_create_early_status_callback():
    mock_controller = MagicMock()
    callback = _create_early_status_callback(mock_controller)

    # Test error
    with patch("backend.core.bootstrap.main.logger.error") as mock_err:
        callback("error", RuntimeStatus.ERROR_MEMORY, "bad thing")
        assert mock_err.called
        mock_controller.state.set_last_error.assert_called_with(
            "bad thing", source="main._early_status_callback"
        )


@patch("backend.core.bootstrap.main.read_input")
def test_create_event_handler(mock_read_input):
    config = AppConfig()
    mock_event_stream = MagicMock()
    handler = _create_event_handler(config, False, None, MagicMock(), mock_event_stream)

    # Trigger observation
    obs = AgentStateChangedObservation(
        agent_state=AgentState.AWAITING_USER_INPUT, content="waiting"
    )
    mock_read_input.return_value = "hello"

    handler(obs)
    mock_event_stream.add_event.assert_called()
    assert "hello" in mock_event_stream.add_event.call_args[0][0].content


@patch("backend.core.bootstrap.main.os.makedirs")
@patch("backend.core.bootstrap.main.open", create=True)
@patch("backend.core.bootstrap.main.json.dump")
def test_save_trajectory(mock_json, mock_open, mock_mkdir):
    config = AppConfig()
    config.save_transcript_path = "/tmp/trajectories"
    mock_controller = MagicMock()
    mock_controller.get_transcript.return_value = {"events": []}

    _save_trajectory(config, "session1", mock_controller)

    mock_mkdir.assert_called()
    mock_json.assert_called()


@patch("backend.core.bootstrap.main.ReplayManager.get_replay_events")
@patch("backend.core.bootstrap.main.Path.exists", return_value=True)
@patch("backend.core.bootstrap.main.Path.is_file", return_value=True)
@patch("backend.core.bootstrap.main.open", create=True)
def test_load_replay_log(mock_open, mock_is_file, mock_exists, mock_get_events):
    mock_get_events.return_value = [
        MessageAction(content="task"),
        MessageAction(content="next"),
    ]

    # Mock json.load to return a dict, so ReplayManager can use it
    with patch("json.load") as mock_json_load:
        mock_json_load.return_value = {}
        events, initial = load_replay_log("path.json")

    assert cast(Any, initial).content == "task"
    assert events is not None
    assert len(events) == 1
    assert cast(Any, events[0]).content == "next"


@patch("backend.core.bootstrap.main._initialize_session_components")
@patch("backend.core.bootstrap.main._setup_runtime_for_controller")
@patch("backend.core.bootstrap.main._execute_controller_lifecycle")
@patch("backend.core.bootstrap.main._save_trajectory")
@pytest.mark.asyncio
async def test_run_controller_full(mock_save, mock_exec, mock_setup, mock_init):
    config = AppConfig()
    mock_init.return_value = ("sid", MagicMock(), MagicMock(), config, MagicMock())
    mock_setup.return_value = (MagicMock(), "/tmp", MagicMock())
    mock_exec.return_value = MagicMock()

    action = MessageAction(content="hi")
    await run_controller(config, action)

    mock_init.assert_called()
    mock_setup.assert_called()
    mock_exec.assert_called()


@patch("backend.core.bootstrap.main.run_agent_until_done", new_callable=AsyncMock)
@pytest.mark.asyncio
async def test_run_agent_loop_basic(mock_until_done):
    mock_runtime = AsyncMock()
    mock_controller = MagicMock()

    await _run_agent_loop(mock_controller, mock_runtime, MagicMock())

    mock_until_done.assert_called_once()


@patch("backend.core.bootstrap.main._setup_runtime_and_repo")
def test_setup_runtime_for_controller(mock_setup_repo):
    config = AppConfig()
    mock_runtime = MagicMock()
    mock_acquire = MagicMock()
    mock_acquire.runtime = mock_runtime
    mock_acquire.repo_directory = "/tmp"
    mock_setup_repo.return_value = mock_acquire

    rt, repo, acq = _setup_runtime_for_controller(
        config, MagicMock(), "sid", True, MagicMock(), None
    )

    assert rt is mock_runtime
    assert repo == "/tmp"
    assert acq is mock_acquire

    # Test passing runtime
    rt2, repo2, acq2 = _setup_runtime_for_controller(
        config, MagicMock(), "sid", True, MagicMock(), mock_runtime
    )
    assert rt2 is mock_runtime
    assert repo2 is None


@patch("backend.core.bootstrap.main._setup_memory_and_mcp")
@patch("backend.core.bootstrap.main._setup_replay_events")
@patch("backend.core.bootstrap.main.create_controller")
@patch("backend.core.bootstrap.main._attach_status_callback")
@patch("backend.core.bootstrap.main._setup_initial_events")
@patch("backend.core.bootstrap.main._run_agent_loop")
@patch("backend.core.bootstrap.main._persist_controller_state", new_callable=AsyncMock)
@pytest.mark.asyncio
async def test_execute_controller_lifecycle(
    mock_persist,
    mock_run_loop,
    mock_initial,
    mock_attach,
    mock_create_c,
    mock_replay,
    mock_sm,
):
    config = AppConfig()
    mock_runtime = MagicMock()
    mock_runtime.event_stream = MagicMock()
    mock_agent = MagicMock()
    mock_controller = MagicMock()
    mock_controller.close = AsyncMock()
    mock_create_c.return_value = (mock_controller, MagicMock())
    mock_replay.return_value = (None, MessageAction(content="hi"))

    await _execute_controller_lifecycle(
        config_=config,
        runtime=mock_runtime,
        session_id="sid",
        repo_directory="/tmp",
        agent=mock_agent,
        conversation_stats=MagicMock(),
        initial_action=MessageAction(content="hi"),
        exit_on_message=False,
        fake_user_response_fn=None,
        memory=None,
        conversation_instructions=None,
    )

    mock_sm.assert_called()
    mock_create_c.assert_called()
    mock_run_loop.assert_called()
