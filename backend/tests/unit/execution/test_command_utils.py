"""Tests for backend.execution.utils.command — startup command helpers."""

from __future__ import annotations

from types import SimpleNamespace
from typing import cast
from unittest.mock import MagicMock

from backend.execution.plugins.requirement import PluginRequirement
from backend.execution.utils.command import (
    _build_plugin_args,
    _validate_and_get_username,
    _validate_env_part,
    get_action_execution_server_startup_command,
)

# ---------------------------------------------------------------------------
# _build_plugin_args
# ---------------------------------------------------------------------------


class TestBuildPluginArgs:
    """Tests for _build_plugin_args."""

    def test_no_plugins(self):
        assert _build_plugin_args(None) == []
        assert _build_plugin_args([]) == []

    def test_single_plugin(self):
        plugin = SimpleNamespace(name='myplugin')
        result = _build_plugin_args([cast(PluginRequirement, plugin)])
        assert result == ['--plugins', 'myplugin']

    def test_multiple_plugins(self):
        plugins = [
            cast(PluginRequirement, SimpleNamespace(name='a')),
            cast(PluginRequirement, SimpleNamespace(name='b')),
        ]
        result = _build_plugin_args(plugins)
        assert result == ['--plugins', 'a', 'b']


# ---------------------------------------------------------------------------
# _validate_env_part
# ---------------------------------------------------------------------------


class TestValidateEnvPart:
    """Tests for _validate_env_part."""

    def test_valid_part(self):
        assert _validate_env_part('openended') is True

    def test_empty_part(self):
        assert _validate_env_part('') is False

    def test_dangerous_semicolon(self):
        assert _validate_env_part('hello;world') is False

    def test_dangerous_pipe(self):
        assert _validate_env_part('hello|world') is False

    def test_dangerous_backtick(self):
        assert _validate_env_part('hello`cmd`') is False

    def test_dangerous_dollar(self):
        assert _validate_env_part('$HOME') is False

    def test_dangerous_ampersand(self):
        assert _validate_env_part('a&b') is False

    def test_dangerous_quotes(self):
        assert _validate_env_part('he"lo') is False
        assert _validate_env_part("he'lo") is False

    def test_dangerous_backslash(self):
        assert _validate_env_part('a\\b') is False


# ---------------------------------------------------------------------------
# _validate_and_get_username
# ---------------------------------------------------------------------------


class TestValidateAndGetUsername:
    """Tests for _validate_and_get_username."""

    def test_default_runtime_user(self):
        assert _validate_and_get_username(None, True) == 'app'

    def test_default_root_user(self):
        assert _validate_and_get_username(None, False) == 'root'

    def test_override_username(self):
        assert _validate_and_get_username('myuser', True) == 'myuser'

    def test_dangerous_username_rejected(self):
        result = _validate_and_get_username('user;cmd', True)
        assert result == 'app'  # falls back to default

    def test_space_in_username_rejected(self):
        result = _validate_and_get_username('user name', False)
        assert result == 'root'

    def test_newline_in_username_rejected(self):
        result = _validate_and_get_username('user\ncmd', True)
        assert result == 'app'


# ---------------------------------------------------------------------------
# get_action_execution_server_startup_command
# ---------------------------------------------------------------------------


class TestGetStartupCommand:
    """Tests for get_action_execution_server_startup_command."""

    def _make_config(
        self,
        *,
        run_as_runtime_user=True,
        enable_browser=True,
        workspace_mount='/workspace',
    ):
        cfg = MagicMock()
        cfg.run_as_runtime_user = run_as_runtime_user
        cfg.enable_browser = enable_browser
        cfg.workspace_mount_path_in_runtime = workspace_mount
        return cfg

    def test_basic_command(self):
        cfg = self._make_config()
        cmd = get_action_execution_server_startup_command(
            server_port=8080,
            plugins=[],
            app_config=cfg,
            python_prefix=[],
        )
        assert '8080' in cmd
        assert '--working-dir' in cmd
        assert '/workspace' in cmd
        assert '--username' in cmd

    def test_browser_disabled(self):
        cfg = self._make_config(enable_browser=False)
        cmd = get_action_execution_server_startup_command(
            server_port=8080,
            plugins=[],
            app_config=cfg,
            python_prefix=[],
        )
        assert '--no-enable-browser' in cmd

    def test_browser_enabled(self):
        cfg = self._make_config(enable_browser=True)
        cmd = get_action_execution_server_startup_command(
            server_port=8080,
            plugins=[],
            app_config=cfg,
            python_prefix=[],
        )
        assert '--no-enable-browser' not in cmd

    def test_override_user_id(self):
        cfg = self._make_config()
        cmd = get_action_execution_server_startup_command(
            server_port=8080,
            plugins=[],
            app_config=cfg,
            python_prefix=[],
            override_user_id=9999,
        )
        assert '9999' in cmd

    def test_plugins_included(self):
        cfg = self._make_config()
        plugins = [cast(PluginRequirement, SimpleNamespace(name='plugA'))]
        cmd = get_action_execution_server_startup_command(
            server_port=8080,
            plugins=plugins,
            app_config=cfg,
            python_prefix=[],
        )
        assert '--plugins' in cmd
        assert 'plugA' in cmd

    def test_no_none_in_result(self):
        cfg = self._make_config()
        cmd = get_action_execution_server_startup_command(
            server_port=8080,
            plugins=[],
            app_config=cfg,
            python_prefix=[],
        )
        assert None not in cmd
