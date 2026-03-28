"""Unit tests for backend.execution.env_manager — EnvManagerMixin."""

from __future__ import annotations

import json
import os
from typing import Any
from unittest.mock import patch

import pytest

from backend.execution.env_manager import EnvManagerMixin


# ── Helpers ──────────────────────────────────────────────────────────


class _FakeRuntime(EnvManagerMixin):
    """Concrete subclass for testing the mixin."""

    def __init__(self, *, windows: bool = False):
        self._windows = windows
        self._last_action: Any = None
        self._run_result: Any = None

    def _uses_windows_shell(self) -> bool:
        return self._windows

    def run(self, action):
        self._last_action = action
        if self._run_result is not None:
            return self._run_result
        from backend.ledger.observation import CmdOutputObservation

        return CmdOutputObservation(
            content="", command_id=0, command=action.command, exit_code=0
        )


# ── _build_powershell_env_cmd ────────────────────────────────────────


class TestBuildPowershellEnvCmd:
    def test_single_var(self):
        rt = _FakeRuntime()
        cmd = rt._build_powershell_env_cmd({"MY_KEY": "my_value"})
        assert '$env:MY_KEY = "my_value"' in cmd

    def test_multiple_vars(self):
        rt = _FakeRuntime()
        cmd = rt._build_powershell_env_cmd({"A": "1", "B": "2"})
        assert "$env:A" in cmd
        assert "$env:B" in cmd
        assert cmd.count(";") >= 1

    def test_empty_dict(self):
        rt = _FakeRuntime()
        cmd = rt._build_powershell_env_cmd({})
        assert cmd == ""

    def test_special_characters_json_escaped(self):
        rt = _FakeRuntime()
        cmd = rt._build_powershell_env_cmd({"KEY": 'val"ue'})
        assert json.dumps('val"ue') in cmd

    def test_spaces_in_value(self):
        rt = _FakeRuntime()
        cmd = rt._build_powershell_env_cmd({"PATH": "/usr/bin /usr/local"})
        assert json.dumps("/usr/bin /usr/local") in cmd


# ── _build_bash_env_commands ─────────────────────────────────────────


class TestBuildBashEnvCommands:
    def test_single_var(self):
        rt = _FakeRuntime()
        cmd, bashrc_cmd = rt._build_bash_env_commands({"MY_KEY": "my_value"})
        assert "export MY_KEY=" in cmd
        assert json.dumps("my_value") in cmd
        assert "export MY_KEY=" in bashrc_cmd
        assert ".bashrc" in bashrc_cmd

    def test_multiple_vars(self):
        rt = _FakeRuntime()
        cmd, bashrc_cmd = rt._build_bash_env_commands({"A": "1", "B": "2"})
        assert "export A=" in cmd
        assert "export B=" in cmd
        assert ".bashrc" in bashrc_cmd

    def test_empty_dict(self):
        rt = _FakeRuntime()
        cmd, bashrc_cmd = rt._build_bash_env_commands({})
        assert cmd == ""
        assert bashrc_cmd == ""

    def test_bashrc_uses_grep_to_avoid_duplicates(self):
        rt = _FakeRuntime()
        _, bashrc_cmd = rt._build_bash_env_commands({"MY_KEY": "val"})
        assert "grep -q" in bashrc_cmd
        assert "^export MY_KEY=" in bashrc_cmd


# ── _add_env_vars_to_powershell ──────────────────────────────────────


class TestAddEnvVarsToPowershell:
    def test_success(self):
        rt = _FakeRuntime(windows=True)
        rt._add_env_vars_to_powershell({"KEY": "val"})
        assert rt._last_action is not None
        assert "$env:KEY" in rt._last_action.command

    def test_empty_dict_skips(self):
        rt = _FakeRuntime(windows=True)
        rt._add_env_vars_to_powershell({})
        assert rt._last_action is None

    def test_failure_raises_runtime_error(self):
        from backend.ledger.observation import CmdOutputObservation

        rt = _FakeRuntime(windows=True)
        rt._run_result = CmdOutputObservation(
            content="error", command_id=0, command="", exit_code=1
        )
        with pytest.raises(RuntimeError, match="Failed to add env vars"):
            rt._add_env_vars_to_powershell({"KEY": "val"})

    def test_non_cmd_observation_raises(self):
        from backend.ledger.observation.error import ErrorObservation

        rt = _FakeRuntime(windows=True)
        rt._run_result = ErrorObservation(content="error")
        with pytest.raises(RuntimeError, match="Failed to add env vars"):
            rt._add_env_vars_to_powershell({"KEY": "val"})


# ── _add_env_vars_to_bash ────────────────────────────────────────────


class TestAddEnvVarsToBash:
    def test_success(self):
        rt = _FakeRuntime(windows=False)
        rt._add_env_vars_to_bash({"KEY": "val"})
        assert rt._last_action is not None

    def test_empty_dict_skips(self):
        rt = _FakeRuntime(windows=False)
        rt._add_env_vars_to_bash({})
        assert rt._last_action is None

    def test_session_failure_raises(self):
        from backend.ledger.observation import CmdOutputObservation

        rt = _FakeRuntime(windows=False)
        rt._run_result = CmdOutputObservation(
            content="error", command_id=0, command="", exit_code=1
        )
        with pytest.raises(RuntimeError, match="Failed to add env vars"):
            rt._add_env_vars_to_bash({"KEY": "val"})


# ── add_env_vars (public API) ────────────────────────────────────────


class TestAddEnvVars:
    def test_uppercases_keys(self):
        rt = _FakeRuntime(windows=False)
        with patch.dict(os.environ, {}, clear=False):
            rt.add_env_vars({"my_key": "value"})
        # Should have been uppercased
        assert rt._last_action is not None
        assert "MY_KEY" in rt._last_action.command

    def test_updates_os_environ(self):
        rt = _FakeRuntime()
        with patch.dict(os.environ, {}, clear=False):
            rt.add_env_vars({"test_env_var_xyz": "123"})
            assert os.environ.get("TEST_ENV_VAR_XYZ") == "123"

    def test_powershell_path_for_windows(self):
        rt = _FakeRuntime(windows=True)
        with patch.dict(os.environ, {}, clear=False):
            rt.add_env_vars({"key": "val"})
        assert "$env:KEY" in rt._last_action.command

    def test_bash_path_for_linux(self):
        rt = _FakeRuntime(windows=False)
        with patch.dict(os.environ, {}, clear=False):
            rt.add_env_vars({"key": "val"})
        assert "export KEY=" in rt._last_action.command

    def test_shell_failure_logs_warning_but_no_raise(self):
        from backend.ledger.observation import CmdOutputObservation

        rt = _FakeRuntime(windows=False)
        rt._run_result = CmdOutputObservation(
            content="error", command_id=0, command="", exit_code=1
        )
        # Should not raise — just log warning
        with patch.dict(os.environ, {}, clear=False):
            rt.add_env_vars({"key": "val"})  # no exception
