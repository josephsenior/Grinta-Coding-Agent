"""Tests for backend.core.bootstrap.setup — framework initialization helpers."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from backend.execution.plugins.requirement import PluginRequirement
from backend.core.config.app_config import AppConfig
from backend.core.bootstrap.setup import (
    filter_plugins_by_config,
    generate_sid,
    create_runtime,
    get_provider_tokens,
    initialize_repository_for_runtime,
    create_memory,
    create_agent,
    create_controller,
)


def test_generate_sid():
    sid1 = generate_sid(AppConfig(), "session1")
    assert len(sid1) <= 32
    assert "session1" in sid1

    sid2 = generate_sid(AppConfig(), "a" * 50)
    assert len(sid2) == 32
    assert sid2.startswith("a" * 16)


def test_filter_plugins_by_config():
    mock_plugin = MagicMock(spec=PluginRequirement)
    mock_plugin.name = "plugin1"
    plugins: list[PluginRequirement] = [mock_plugin]

    # No agent, no config
    assert filter_plugins_by_config(plugins) == plugins

    # Agent with disabled plugins (hits 90-91)
    mock_agent = MagicMock()
    mock_agent.config.disabled_plugins = ["plugin1"]
    # Patch the logger in the core module to ensure it's captured
    with patch("backend.core.logger.app_logger.info") as mock_info:
        assert filter_plugins_by_config(plugins, agent=mock_agent) == []
        mock_info.assert_called()

    # Config with agent class name
    mock_config = MagicMock(spec=AppConfig)
    mock_agent_config = MagicMock()
    mock_agent_config.disabled_plugins = ["plugin1"]
    mock_config.get_agent_config.return_value = mock_agent_config
    assert (
        filter_plugins_by_config(plugins, config=mock_config, agent_cls_name="MyAgent")
        == []
    )


def test_filter_plugins_by_config_honors_app_plugins_env():
    plugin1 = MagicMock(spec=PluginRequirement)
    plugin1.name = "plugin1"
    plugin2 = MagicMock(spec=PluginRequirement)
    plugin2.name = "plugin2"
    plugins: list[PluginRequirement] = [plugin1, plugin2]

    with patch.dict("os.environ", {"APP_PLUGINS": "plugin1"}, clear=False):
        assert filter_plugins_by_config(plugins) == [plugin1]


@patch("backend.orchestration.agent.Agent.get_cls")
def test_ensure_agent_class_available_success(mock_get_cls):
    from backend.core.bootstrap.setup import _ensure_agent_class_available

    _ensure_agent_class_available("any")
    mock_get_cls.assert_called_with("any")


@patch("backend.core.bootstrap.setup.get_file_store")
@patch("backend.core.bootstrap.setup.EventStream")
@patch("backend.execution.runtime_factory.get_runtime_cls")
def test_create_runtime_sid_from_stream(
    mock_get_runtime_cls, mock_event_stream_cls, mock_get_file_store
):
    mock_config = MagicMock(spec=AppConfig)
    mock_config.runtime = "docker"
    mock_config.default_agent = "agent"

    # event_stream provided (hits line 144)
    mock_event_stream = MagicMock()
    mock_event_stream.sid = "stream_sid"

    mock_runtime_cls = MagicMock()
    mock_runtime_cls.__name__ = "Mock"
    mock_get_runtime_cls.return_value = mock_runtime_cls

    with patch("backend.orchestration.agent.Agent.get_cls") as mock_get_cls:
        mock_agent_cls = MagicMock()
        mock_agent_cls.runtime_plugins = []
        mock_agent_cls.__name__ = "Agent"  # Fix attributed error __name__
        mock_get_cls.return_value = mock_agent_cls
        create_runtime(
            mock_config, event_stream=mock_event_stream, llm_registry=MagicMock()
        )

    mock_runtime_cls.assert_called()
    assert mock_runtime_cls.call_args[1]["sid"] == "stream_sid"


@patch("backend.core.bootstrap.setup.get_file_store")
@patch("backend.core.bootstrap.setup.EventStream")
@patch("backend.execution.runtime_factory.get_runtime_cls")
def test_create_runtime(
    mock_get_runtime_cls, mock_event_stream_cls, mock_get_file_store
):
    mock_config = MagicMock(spec=AppConfig)
    mock_config.file_store = "memory"
    mock_config.local_data_root = "/tmp"
    mock_config.runtime = "docker"
    mock_config.default_agent = "agent"

    mock_runtime_cls = MagicMock()
    mock_runtime_cls.__name__ = "MockRuntime"
    mock_get_runtime_cls.return_value = mock_runtime_cls

    mock_runtime = MagicMock()
    mock_runtime.plugins = []
    mock_runtime_cls.return_value = mock_runtime

    mock_agent = MagicMock()
    type(mock_agent).runtime_plugins = []

    # We need to mock Agent.get_cls too if agent is None
    with patch("backend.orchestration.agent.Agent.get_cls") as mock_get_agent_cls:
        mock_agent_cls = MagicMock()
        mock_agent_cls.runtime_plugins = []
        mock_agent_cls.__name__ = "Agent"
        mock_get_agent_cls.return_value = mock_agent_cls

        # provide llm_registry to avoid instantiation
        create_runtime(mock_config, agent=mock_agent, llm_registry=MagicMock())

    mock_runtime_cls.assert_called()


@patch("backend.core.bootstrap.setup.State.restore_from_session")
@patch("backend.core.bootstrap.setup.SessionOrchestrator")
def test_create_controller(mock_controller_cls, mock_restore):
    mock_agent = MagicMock()
    mock_runtime = MagicMock()
    mock_runtime.event_stream.sid = "sid"
    mock_runtime.event_stream.file_store = MagicMock()
    mock_runtime.security_analyzer = MagicMock()

    mock_config = MagicMock(spec=AppConfig)
    mock_config.max_iterations = 10
    mock_config.max_budget_per_task = 100
    mock_config.pending_action_timeout = 60.0
    mock_config.get_agent_to_llm_config_map.return_value = {}
    mock_config.security = MagicMock()
    mock_config.security.confirmation_mode = False

    # Test success restoration
    mock_restore.return_value = MagicMock()
    create_controller(mock_agent, mock_runtime, mock_config, MagicMock())
    mock_controller_cls.assert_called()

    # Test restoration failure (line 347-348)
    mock_restore.side_effect = Exception("failed")
    create_controller(mock_agent, mock_runtime, mock_config, MagicMock())


def test_create_memory_extended():
    mock_runtime = MagicMock()
    mock_runtime.workspace_root = "/work"
    mock_runtime.get_playbooks_from_selected_repo.return_value = []
    mock_event_stream = MagicMock()

    # Test with repository info (line 264)
    memory = create_memory(
        mock_runtime,
        mock_event_stream,
        "sid",
        selected_repository="repo",
        repo_directory="/path",
    )
    assert memory.sid == "sid"


@patch("backend.core.bootstrap.setup.importlib.import_module")
@patch("backend.orchestration.agent.Agent.get_cls")
def test_create_agent_retry(mock_get_cls, mock_import):
    mock_config = MagicMock(spec=AppConfig)
    mock_config.default_agent = "my_agent"
    mock_config.get_agent_config.return_value = MagicMock()

    from backend.core.errors import AgentNotRegisteredError

    # 1. create_agent -> exc
    # 2. _ensure... -> exc
    # 3. _ensure... (after import) -> success
    # 4. create_agent (final) -> success
    mock_agent_cls = MagicMock()
    mock_get_cls.side_effect = [
        AgentNotRegisteredError("my_agent"),
        AgentNotRegisteredError("my_agent"),
        mock_agent_cls,
        mock_agent_cls,
    ]

    llm_registry = MagicMock()
    create_agent(mock_config, llm_registry)
    mock_import.assert_called_with("app.engine")


@patch("backend.orchestration.agent.Agent.get_cls")
def test_ensure_agent_class_available_fatal(mock_get_cls):
    from backend.core.bootstrap.setup import _ensure_agent_class_available
    from backend.core.errors import AgentNotRegisteredError

    mock_get_cls.side_effect = AgentNotRegisteredError("any")

    with pytest.raises(AgentNotRegisteredError):
        _ensure_agent_class_available("any")


def test_create_controller_no_stream():
    mock_agent = MagicMock()
    mock_runtime = MagicMock()
    mock_runtime.event_stream = None  # Trigger line 337
    with pytest.raises(
        RuntimeError, match="Runtime does not have an initialized event stream"
    ):
        create_controller(mock_agent, mock_runtime, MagicMock(), MagicMock())


@patch("backend.core.bootstrap.setup.UserSecrets")
def test_create_secret_store_logic(mock_user_secrets):
    from backend.core.bootstrap.setup import _create_secret_store

    assert _create_secret_store({}) is None
    _create_secret_store({"a": 1})
    mock_user_secrets.assert_called_once()


@patch("backend.core.bootstrap.setup._create_secret_store")
def test_get_provider_tokens_none(mock_create):
    mock_create.return_value = None
    assert get_provider_tokens() is None


@patch("backend.core.bootstrap.setup.get_provider_tokens")
@patch("backend.core.bootstrap.setup.call_async_from_sync")
def test_initialize_repository_for_runtime_no_tokens(mock_call_async, mock_get_tokens):
    mock_runtime = MagicMock()
    mock_call_async.return_value = "/path"
    mock_get_tokens.return_value = {"github": "token"}

    res = initialize_repository_for_runtime(mock_runtime)
    assert res == "/path"

