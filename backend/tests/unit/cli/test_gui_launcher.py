"""Tests for GUI launcher functionality.

Tests server launch, configuration, and port checking.
"""

import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

from backend.cli.gui_launcher import ensure_config_dir_exists, launch_gui_server


class TestEnsureConfigDirExists(unittest.TestCase):
    """Tests for ensure_config_dir_exists() configuration directory setup."""

    @patch("pathlib.Path.home")
    @patch("pathlib.Path.mkdir")
    def test_creates_config_dir(self, mock_mkdir: Mock, mock_home: Mock) -> None:
        """Test creates .Forge directory in user home."""
        mock_home_path = MagicMock(spec=Path)
        mock_home.return_value = mock_home_path
        mock_config_path = MagicMock(spec=Path)
        mock_home_path.__truediv__.return_value = mock_config_path

        result = ensure_config_dir_exists()

        mock_home_path.__truediv__.assert_called_once_with(".Forge")
        mock_config_path.mkdir.assert_called_once_with(exist_ok=True)
        self.assertEqual(result, mock_config_path)

    @patch("pathlib.Path.home")
    def test_returns_config_dir_path(self, mock_home: Mock) -> None:
        """Test returns Path object for config directory."""
        mock_home_path = MagicMock(spec=Path)
        mock_home.return_value = mock_home_path
        mock_config_path = MagicMock(spec=Path)
        mock_home_path.__truediv__.return_value = mock_config_path

        result = ensure_config_dir_exists()

        self.assertIsInstance(result, type(mock_config_path))


class TestLaunchGUIServer(unittest.TestCase):
    """Tests for launch_gui_server() server orchestration."""

    @patch("backend.cli.gui_launcher.ensure_config_dir_exists")
    @patch("pathlib.Path.cwd")
    @patch("pathlib.Path.exists")
    @patch("socket.socket")
    @patch("subprocess.run")
    @patch("builtins.print")
    def test_launches_uvicorn_server(
        self,
        mock_print: Mock,
        mock_subprocess_run: Mock,
        mock_socket: Mock,
        mock_exists: Mock,
        mock_cwd: Mock,
        mock_ensure_config: Mock,
    ) -> None:
        """Test launches uvicorn server with correct arguments."""
        # Setup mocks
        mock_cwd.return_value = Path("/home/user/project")
        mock_exists.return_value = False

        mock_sock_instance = MagicMock()
        mock_sock_instance.connect_ex.return_value = 1  # Port not in use
        mock_socket.return_value = mock_sock_instance

        # Call function
        launch_gui_server()

        # Verify subprocess.run was called with uvicorn command
        mock_subprocess_run.assert_called_once()
        call_args = mock_subprocess_run.call_args
        cmd = call_args[0][0]

        self.assertEqual(cmd[0], sys.executable)
        self.assertEqual(cmd[1], "-m")
        self.assertEqual(cmd[2], "uvicorn")
        self.assertEqual(cmd[3], "backend.api.listen:app")
        self.assertIn("3000", cmd)

    @patch("backend.cli.gui_launcher.ensure_config_dir_exists")
    @patch("pathlib.Path.cwd")
    @patch("pathlib.Path.exists")
    @patch("socket.socket")
    @patch("subprocess.run")
    @patch("builtins.print")
    def test_sets_runtime_env_var(
        self,
        mock_print: Mock,
        mock_subprocess_run: Mock,
        mock_socket: Mock,
        mock_exists: Mock,
        mock_cwd: Mock,
        mock_ensure_config: Mock,
    ) -> None:
        """Test sets FORGE_RUNTIME environment variable to 'local'."""
        mock_cwd.return_value = Path("/home/user/project")
        mock_exists.return_value = False

        mock_sock_instance = MagicMock()
        mock_sock_instance.connect_ex.return_value = 1
        mock_socket.return_value = mock_sock_instance

        launch_gui_server()

        call_kwargs = mock_subprocess_run.call_args[1]
        env = call_kwargs["env"]
        self.assertEqual(env["FORGE_RUNTIME"], "local")

    @patch("backend.cli.gui_launcher.ensure_config_dir_exists")
    @patch("pathlib.Path.cwd")
    @patch("socket.socket")
    @patch("subprocess.run")
    @patch("builtins.print")
    def test_checks_for_agent_yaml(
        self,
        mock_print: Mock,
        mock_subprocess_run: Mock,
        mock_socket: Mock,
        mock_cwd: Mock,
        mock_ensure_config: Mock,
    ) -> None:
        """Test checks for agent.yaml in current directory."""
        mock_cwd_path = MagicMock(spec=Path)
        mock_agent_yaml = MagicMock()
        mock_agent_yaml.exists.return_value = True
        mock_cwd_path.__truediv__.return_value = mock_agent_yaml

        with patch("pathlib.Path.cwd", return_value=mock_cwd_path):
            mock_sock_instance = MagicMock()
            mock_sock_instance.connect_ex.return_value = 1
            mock_socket.return_value = mock_sock_instance

            launch_gui_server()

        # Should print message about agent config
        printed_output = "".join(str(call[0][0]) for call in mock_print.call_args_list)
        self.assertIn("agent configuration", printed_output.lower())

    @patch("backend.cli.gui_launcher.ensure_config_dir_exists")
    @patch("pathlib.Path.cwd")
    @patch("pathlib.Path.exists")
    @patch("socket.socket")
    @patch("subprocess.run")
    @patch("builtins.print")
    def test_warns_if_port_in_use(
        self,
        mock_print: Mock,
        mock_subprocess_run: Mock,
        mock_socket: Mock,
        mock_exists: Mock,
        mock_cwd: Mock,
        mock_ensure_config: Mock,
    ) -> None:
        """Test warns if port 3000 is already in use."""
        mock_cwd.return_value = Path("/home/user/project")
        mock_exists.return_value = False

        mock_sock_instance = MagicMock()
        mock_sock_instance.connect_ex.return_value = 0  # Port in use!
        mock_socket.return_value = mock_sock_instance

        launch_gui_server()

        # Should print warning
        printed_output = "".join(str(call[0][0]) for call in mock_print.call_args_list)
        self.assertIn("port 3000", printed_output.lower())
        self.assertIn("in use", printed_output.lower())

    @patch("backend.cli.gui_launcher.ensure_config_dir_exists")
    @patch("pathlib.Path.cwd")
    @patch("pathlib.Path.exists")
    @patch("socket.socket")
    @patch("subprocess.run")
    @patch("sys.exit")
    def test_exits_on_subprocess_error(
        self,
        mock_exit: Mock,
        mock_subprocess_run: Mock,
        mock_socket: Mock,
        mock_exists: Mock,
        mock_cwd: Mock,
        mock_ensure_config: Mock,
    ) -> None:
        """Test exits with code 1 on subprocess error."""
        mock_cwd.return_value = Path("/home/user/project")
        mock_exists.return_value = False

        mock_sock_instance = MagicMock()
        mock_sock_instance.connect_ex.return_value = 1
        mock_socket.return_value = mock_sock_instance

        mock_subprocess_run.side_effect = subprocess.CalledProcessError(
            returncode=1, cmd="uvicorn"
        )

        launch_gui_server()

        mock_exit.assert_called_once_with(1)

    @patch("backend.cli.gui_launcher.ensure_config_dir_exists")
    @patch("pathlib.Path.cwd")
    @patch("pathlib.Path.exists")
    @patch("socket.socket")
    @patch("subprocess.run")
    @patch("sys.exit")
    def test_exits_gracefully_on_keyboard_interrupt(
        self,
        mock_exit: Mock,
        mock_subprocess_run: Mock,
        mock_socket: Mock,
        mock_exists: Mock,
        mock_cwd: Mock,
        mock_ensure_config: Mock,
    ) -> None:
        """Test handles Ctrl+C gracefully."""
        mock_cwd.return_value = Path("/home/user/project")
        mock_exists.return_value = False

        mock_sock_instance = MagicMock()
        mock_sock_instance.connect_ex.return_value = 1
        mock_socket.return_value = mock_sock_instance

        mock_subprocess_run.side_effect = KeyboardInterrupt()

        launch_gui_server()

        mock_exit.assert_called_once_with(0)

    @patch("backend.cli.gui_launcher.ensure_config_dir_exists")
    @patch("pathlib.Path.cwd")
    @patch("pathlib.Path.exists")
    @patch("socket.socket")
    @patch("subprocess.run")
    @patch("sys.exit")
    def test_exits_on_unexpected_error(
        self,
        mock_exit: Mock,
        mock_subprocess_run: Mock,
        mock_socket: Mock,
        mock_exists: Mock,
        mock_cwd: Mock,
        mock_ensure_config: Mock,
    ) -> None:
        """Test handles unexpected errors."""
        mock_cwd.return_value = Path("/home/user/project")
        mock_exists.return_value = False

        mock_sock_instance = MagicMock()
        mock_sock_instance.connect_ex.return_value = 1
        mock_socket.return_value = mock_sock_instance

        mock_subprocess_run.side_effect = RuntimeError("Unexpected failure")

        launch_gui_server()

        mock_exit.assert_called_once_with(1)


if __name__ == "__main__":
    unittest.main()
