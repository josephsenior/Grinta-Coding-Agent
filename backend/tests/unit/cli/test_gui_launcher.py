"""Tests for GUI launcher functionality."""

import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

from backend.cli.gui_launcher import ensure_config_dir_exists, launch_gui_server


class TestEnsureConfigDirExists(unittest.TestCase):
    """Tests for ensure_config_dir_exists() configuration directory setup."""

    @patch("backend.cli.gui_launcher.get_app_settings_root")
    @patch("backend.cli.gui_launcher.Path")
    def test_creates_config_dir(self, mock_path_cls: Mock, mock_get_root: Mock) -> None:
        """Test creates settings directory."""
        mock_get_root.return_value = "/fake/root"
        mock_config_path = MagicMock(spec=Path)
        mock_path_cls.return_value = mock_config_path

        result = ensure_config_dir_exists()

        mock_path_cls.assert_called_once_with("/fake/root")
        mock_config_path.mkdir.assert_called_once_with(parents=True, exist_ok=True)
        self.assertEqual(result, mock_config_path)

    @patch("backend.cli.gui_launcher.get_app_settings_root")
    def test_returns_config_dir_path(self, mock_get_root: Mock) -> None:
        """Test returns Path object for config directory."""
        mock_get_root.return_value = "/fake/root/dir"
        result = ensure_config_dir_exists()

        self.assertIsInstance(result, Path)
        self.assertEqual(str(result), str(Path("/fake/root/dir")))


class TestLaunchGUIServer(unittest.TestCase):
    """Tests for launch_gui_server() server orchestration."""

    @patch("backend.cli.gui_launcher.ensure_config_dir_exists")
    @patch("pathlib.Path.cwd")
    @patch("subprocess.run")
    @patch("builtins.print")
    def test_launches_uvicorn_server(
        self,
        mock_print: Mock,
        mock_subprocess_run: Mock,
        mock_cwd: Mock,
        mock_ensure_config: Mock,
    ) -> None:
        """Test delegates to canonical start_server.py entrypoint."""
        mock_cwd.return_value = Path("/home/user/project")

        launch_gui_server()

        mock_subprocess_run.assert_called_once()
        call_args = mock_subprocess_run.call_args
        cmd = call_args[0][0]

        self.assertEqual(cmd[0], sys.executable)
        self.assertTrue(str(cmd[1]).endswith("start_server.py"))

    @patch("backend.cli.gui_launcher.ensure_config_dir_exists")
    @patch("pathlib.Path.cwd")
    @patch("subprocess.run")
    @patch("builtins.print")
    def test_sets_runtime_env_var(
        self,
        mock_print: Mock,
        mock_subprocess_run: Mock,
        mock_cwd: Mock,
        mock_ensure_config: Mock,
    ) -> None:
        """Test sets FORGE_RUNTIME environment variable to 'local'."""
        mock_cwd.return_value = Path("/home/user/project")

        launch_gui_server()

        call_kwargs = mock_subprocess_run.call_args[1]
        env = call_kwargs["env"]
        self.assertEqual(env["FORGE_RUNTIME"], "local")

    @patch("backend.cli.gui_launcher.ensure_config_dir_exists")
    @patch("pathlib.Path.cwd")
    @patch("subprocess.run")
    @patch("builtins.print")
    def test_checks_for_agent_yaml(
        self,
        mock_print: Mock,
        mock_subprocess_run: Mock,
        mock_cwd: Mock,
        mock_ensure_config: Mock,
    ) -> None:
        """Test checks for agent.yaml in current directory."""
        mock_cwd_path = MagicMock(spec=Path)
        mock_agent_yaml = MagicMock()
        mock_agent_yaml.exists.return_value = True
        mock_cwd_path.__truediv__.return_value = mock_agent_yaml

        with patch("pathlib.Path.cwd", return_value=mock_cwd_path):
            launch_gui_server()

        # Should print message about agent config
        printed_output = "".join(str(call[0][0]) for call in mock_print.call_args_list)
        self.assertIn("agent configuration", printed_output.lower())

    @patch("backend.cli.gui_launcher.ensure_config_dir_exists")
    @patch("pathlib.Path.cwd")
    @patch("subprocess.run")
    @patch("builtins.print")
    def test_prints_canonical_entrypoint_message(
        self,
        mock_print: Mock,
        mock_subprocess_run: Mock,
        mock_cwd: Mock,
        mock_ensure_config: Mock,
    ) -> None:
        """Test tells operators that serve delegates to canonical entrypoint."""
        mock_cwd.return_value = Path("/home/user/project")

        launch_gui_server()

        printed_output = "".join(str(call[0][0]) for call in mock_print.call_args_list)
        self.assertIn("canonical local server entrypoint", printed_output.lower())

    @patch("backend.cli.gui_launcher.ensure_config_dir_exists")
    @patch("pathlib.Path.cwd")
    @patch("subprocess.run")
    @patch("sys.exit")
    def test_exits_on_subprocess_error(
        self,
        mock_exit: Mock,
        mock_subprocess_run: Mock,
        mock_cwd: Mock,
        mock_ensure_config: Mock,
    ) -> None:
        """Test exits with code 1 on subprocess error."""
        mock_cwd.return_value = Path("/home/user/project")

        mock_subprocess_run.side_effect = subprocess.CalledProcessError(
            returncode=1, cmd="uvicorn"
        )

        launch_gui_server()

        mock_exit.assert_called_once_with(1)

    @patch("backend.cli.gui_launcher.ensure_config_dir_exists")
    @patch("pathlib.Path.cwd")
    @patch("subprocess.run")
    @patch("sys.exit")
    def test_exits_gracefully_on_keyboard_interrupt(
        self,
        mock_exit: Mock,
        mock_subprocess_run: Mock,
        mock_cwd: Mock,
        mock_ensure_config: Mock,
    ) -> None:
        """Test handles Ctrl+C gracefully."""
        mock_cwd.return_value = Path("/home/user/project")

        mock_subprocess_run.side_effect = KeyboardInterrupt()

        launch_gui_server()

        mock_exit.assert_called_once_with(0)

    @patch("backend.cli.gui_launcher.ensure_config_dir_exists")
    @patch("pathlib.Path.cwd")
    @patch("subprocess.run")
    @patch("sys.exit")
    def test_exits_on_unexpected_error(
        self,
        mock_exit: Mock,
        mock_subprocess_run: Mock,
        mock_cwd: Mock,
        mock_ensure_config: Mock,
    ) -> None:
        """Test handles unexpected errors."""
        mock_cwd.return_value = Path("/home/user/project")

        mock_subprocess_run.side_effect = RuntimeError("Unexpected failure")

        launch_gui_server()

        mock_exit.assert_called_once_with(1)


if __name__ == "__main__":
    unittest.main()

