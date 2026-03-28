import pytest
import subprocess
from unittest.mock import MagicMock, patch
from backend.execution.utils.simple_bash import SimpleBashSession
from backend.ledger.action import CmdRunAction
from backend.ledger.observation import ErrorObservation

class TestSimpleBashSession:
    @pytest.fixture
    def mock_cancellation(self):
        return MagicMock()

    @pytest.fixture
    def session(self, tmp_path, mock_cancellation):
        # Use a sub-path that doesn't exist to trigger makedirs
        work_dir = tmp_path / "new_bash_dir"
        s = SimpleBashSession(
            work_dir=str(work_dir),
            cancellation_service=mock_cancellation
        )
        s.initialize()
        return s

    def test_initialize_new_dir(self, tmp_path, mock_cancellation):
        """Covers lines 42-43."""
        work_dir = tmp_path / "sub" / "new"
        assert not work_dir.exists()
        s = SimpleBashSession(work_dir=str(work_dir), cancellation_service=mock_cancellation)
        s.initialize()
        assert work_dir.exists()

    def test_execute_uninitialized(self, tmp_path, mock_cancellation):
        s = SimpleBashSession(work_dir=str(tmp_path), cancellation_service=mock_cancellation)
        action = CmdRunAction(command="ls")
        result = s.execute(action)
        assert isinstance(result, ErrorObservation)
        assert "not initialized" in result.content

    def test_execute_interactive_input_error(self, session):
        action = CmdRunAction(command="some input", is_input=True)
        action.set_hard_timeout(10.0)
        result = session.execute(action)
        assert "Interactive input not supported" in result.content

    @patch("subprocess.Popen")
    def test_execute_command_success(self, mock_popen, session):
        mock_process = MagicMock()
        mock_process.communicate.return_value = ("stdout_val", "")
        mock_process.returncode = 0
        mock_popen.return_value = mock_process

        action = CmdRunAction(command="echo hello")
        action.set_hard_timeout(10.0)
        result = session.execute(action)

        assert result.content == "stdout_val"

    @patch("subprocess.Popen")
    def test_execute_command_with_cd(self, mock_popen, session):
        """Covers lines 123, 150."""
        mock_process = MagicMock()
        mock_process.communicate.return_value = ("/new/path", "")
        mock_process.returncode = 0
        mock_popen.return_value = mock_process

        action = CmdRunAction(command="cd /new/path")
        action.set_hard_timeout(10.0)
        session.execute(action)
        # It should have called pwd
        # First call was cd, second was pwd
        assert mock_popen.call_count >= 2

    @patch("subprocess.Popen")
    def test_execute_background_failure_fallback(self, mock_popen, session):
        """Covers lines 103-106."""
        mock_process = MagicMock()
        # First call (nohup) returns non-digit
        mock_process.communicate.side_effect = [
            ("error\n", ""), # nohup attempt
            ("stdout\n", ""), # fallback attempt
        ]
        mock_process.returncode = 0
        mock_popen.return_value = mock_process

        action = CmdRunAction(command="sleep 100 &")
        action.set_hard_timeout(10.0)
        result = session.execute(action)
        assert result.content == "stdout"

    @patch("subprocess.Popen")
    def test_execute_background_registration_exception(self, mock_popen, session):
        """Covers lines 93-94."""
        mock_process = MagicMock()
        mock_process.communicate.return_value = ("123\n", "")
        mock_process.returncode = 0
        mock_popen.return_value = mock_process

        # Mock register_pid to fail
        session._cancellation.register_pid.side_effect = Exception("Reg fail")

        action = CmdRunAction(command="sleep 100 &")
        action.set_hard_timeout(10.0)
        result = session.execute(action)
        assert "[123]" in result.content

    def test_run_command_closed_error(self, session):
        """Covers line 115."""
        session.close()
        with pytest.raises(RuntimeError, match="closed"):
            session._run_command("ls")

    @patch("subprocess.Popen")
    def test_handle_subprocess_timeout(self, mock_popen, session):
        mock_process = MagicMock()
        mock_process.communicate.side_effect = subprocess.TimeoutExpired(cmd="ls", timeout=10)
        mock_popen.return_value = mock_process

        action = CmdRunAction(command="ls")
        action.set_hard_timeout(10.0)
        result = session.execute(action)
        assert "timed out" in result.content
