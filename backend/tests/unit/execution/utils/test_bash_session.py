import json
import os
from unittest.mock import MagicMock, patch

import pytest

from backend.core.constants import CMD_OUTPUT_PS1_BEGIN, CMD_OUTPUT_PS1_END
from backend.ledger.action import CmdRunAction
from backend.ledger.observation import ErrorObservation
from backend.ledger.observation.commands import CmdOutputObservation
from backend.execution.utils.bash import BashCommandStatus, BashSession


def _fake_ps1_json_block(*, working_dir: str, exit_code: int = 0) -> str:
    payload = {
        "pid": 123,
        "exit_code": exit_code,
        "username": "testuser",
        "hostname": "testhost",
        "working_dir": working_dir,
        "py_interpreter_path": "python",
    }
    return f"{CMD_OUTPUT_PS1_BEGIN}{json.dumps(payload)}{CMD_OUTPUT_PS1_END}"

class TestBashSession:
    @pytest.fixture
    def mock_tmux(self):
        with patch("libtmux.Server") as mock_server_class:
            mock_server = mock_server_class.return_value
            mock_session = MagicMock()
            mock_window = MagicMock()
            mock_pane = MagicMock()

            mock_server.new_session.return_value = mock_session
            mock_session.active_window = mock_window
            mock_window.active_pane = mock_pane

            # Mock pane.cmd("capture-pane", ...)
            mock_cmd_result = MagicMock()
            mock_cmd_result.stdout = [""]
            mock_pane.cmd.return_value = mock_cmd_result

            yield {
                "server": mock_server,
                "session": mock_session,
                "window": mock_window,
                "pane": mock_pane
            }

    @pytest.fixture
    def session(self, mock_tmux, tmp_path):
        s = BashSession(work_dir=str(tmp_path))
        s.initialize()
        return s

    def test_initialize(self, session, mock_tmux):
        assert session._initialized
        assert session.server == mock_tmux["server"]
        assert session.session == mock_tmux["session"]
        assert session.window == mock_tmux["window"]
        assert session.pane == mock_tmux["pane"]
        mock_tmux["pane"].send_keys.assert_any_call(
            f'''export PROMPT_COMMAND='export PS1="{session.PS1}"'; export PS2=""'''
        )

    def test_initialize_failure(self, mock_tmux, tmp_path):
        mock_tmux["server"].new_session.return_value = None
        s = BashSession(work_dir=str(tmp_path))
        with pytest.raises(RuntimeError, match="Failed to create tmux session"):
            s.initialize()

    def test_initialize_fails_when_tmux_tmpdir_unwritable(self, tmp_path, monkeypatch):
        s = BashSession(work_dir=str(tmp_path))
        monkeypatch.setenv("TMUX_TMPDIR", str(tmp_path / "tmux"))
        with patch("os.access", return_value=False):
            with pytest.raises(RuntimeError, match="TMUX_TMPDIR .* is not writable"):
                s.initialize()

    def test_initialize_creates_tmux_tmpdir(self, mock_tmux, tmp_path, monkeypatch):
        s = BashSession(work_dir=str(tmp_path))
        monkeypatch.setenv("TMUX_TMPDIR", str(tmp_path / "tmux"))
        with patch("os.makedirs") as mock_makedirs, patch("os.access", return_value=True):
            s.initialize()
        mock_makedirs.assert_called()

    def test_close(self, session, mock_tmux):
        session.close()
        mock_tmux["session"].kill.assert_called_once()
        assert not session._initialized

    def test_execute_not_initialized(self, tmp_path):
        s = BashSession(work_dir=str(tmp_path))
        action = CmdRunAction(command="ls")
        with pytest.raises(RuntimeError, match="not initialized"):
            s.execute(action)

    def test_execute_empty_command_error(self, session):
        action = CmdRunAction(command="")
        result = session.execute(action)
        assert isinstance(result, CmdOutputObservation)
        assert "No previous running command" in result.content

    def test_execute_multiple_commands_error(self, session):
        action = CmdRunAction(command="echo a\necho b")
        result = session.execute(action)
        assert isinstance(result, ErrorObservation)
        assert "Cannot execute multiple commands at once" in result.content

    @patch("backend.execution.utils.bash.should_continue")
    def test_execute_command_success(self, mock_should_continue, session, mock_tmux):
        mock_should_continue.return_value = True
        ps1_full = _fake_ps1_json_block(working_dir=session.work_dir, exit_code=0)

        # We need to mock _get_pane_content to exit the loop eventually
        with patch.object(session, "_get_pane_content") as mock_get_content:
            mock_get_content.side_effect = [
                ps1_full, # execute initial
                ps1_full, # monitor initial
                ps1_full + "\necho hello world\nhello world\n" + ps1_full, # loop update
                ps1_full + "\necho hello world\nhello world\n" + ps1_full,
                ps1_full + "\necho hello world\nhello world\n" + ps1_full,
            ]
            action = CmdRunAction(command="echo hello world")
            action.set_hard_timeout(10.0)

            with patch("time.sleep"):
                result = session.execute(action)

        assert "hello world" in result.content
        assert result.metadata.exit_code == 0

    @patch("backend.execution.utils.bash.should_continue")
    @patch("time.time")
    def test_execute_no_change_timeout(self, mock_time, mock_should_continue, session, mock_tmux):
        mock_should_continue.return_value = True
        def time_gen():
            yield 100
            while True:
                yield 150  # trigger no-change timeout

        mock_time.side_effect = time_gen()

        ps1_full = _fake_ps1_json_block(working_dir=session.work_dir, exit_code=0)
        running_output = ps1_full + "\nsleep 100\n"

        action = CmdRunAction(command="sleep 100")
        action.set_hard_timeout(200.0, blocking=False)

        with patch.object(session, "_get_pane_content") as mock_get_content:
            mock_get_content.side_effect = [
                ps1_full,  # initial prompt (ready)
                running_output,  # command started; no trailing PS1 prompt
                running_output,  # unchanged output triggers no-change timeout
            ]
            with patch("time.sleep"):
                result = session.execute(action)

        assert "no new output" in result.metadata.suffix
        assert session.prev_status == BashCommandStatus.NO_CHANGE_TIMEOUT

    @patch("backend.execution.utils.bash.should_continue")
    @patch("time.time")
    def test_execute_hard_timeout(self, mock_time, mock_should_continue, session, mock_tmux):
        mock_should_continue.return_value = True

        def time_gen():
            yield 100
            while True:
                yield 120  # trigger hard timeout

        mock_time.side_effect = time_gen()

        ps1_full = _fake_ps1_json_block(working_dir=session.work_dir, exit_code=0)
        running_output = ps1_full + "\nsleep 100\n"

        action = CmdRunAction(command="sleep 100")
        action.set_hard_timeout(10.0)

        with patch.object(session, "_get_pane_content") as mock_get_content:
            mock_get_content.side_effect = [
                ps1_full,  # initial prompt (ready)
                running_output,  # command started; no trailing PS1 prompt
                running_output,  # unchanged output triggers hard timeout
            ]
            with patch("time.sleep"):
                result = session.execute(action)

        assert "timed out after 10.0 seconds" in result.metadata.suffix
        assert session.prev_status == BashCommandStatus.HARD_TIMEOUT

    def test_handle_interactive_prompts(self, session, mock_tmux):
        with patch("backend.execution.utils.bash.detect_interactive_prompt", return_value=(True, "y")):
            # Trigger it
            session._handle_interactive_prompts("Proceed? (y/n)", is_input=False)
            mock_tmux["pane"].send_keys.assert_called_with("y", enter=True)

    def test_detect_server_startup(self, session):
        with patch("backend.execution.utils.server_detector.detect_server_from_output") as mock_detect:
            mock_server = MagicMock()
            mock_server.url = "http://localhost:8080"
            mock_detect.return_value = mock_server

            session._detect_server_startup("Listening on port 8080")
            assert session._last_detected_server == mock_server

            # get_detected_server should return and clear it
            assert session.get_detected_server() == mock_server
            assert session.get_detected_server() is None

    def test_is_special_key(self, session):
        assert session._is_special_key("C-c")
        assert not session._is_special_key("ls")

    def test_should_use_su(self, session):
        session.username = "testuser"
        if not hasattr(os, "geteuid"):
            assert session._should_use_su() is False
            return

        with patch("os.geteuid", return_value=0):
            with patch("getpass.getuser", return_value="root"):
                assert session._should_use_su() is True

        with patch("os.geteuid", return_value=1000):
            assert session._should_use_su() is False

    @patch("libtmux.Server")
    def test_get_window_and_pane_with_retry(self, mock_server_class, session):
        mock_session = MagicMock()
        mock_window = MagicMock()
        mock_pane = MagicMock()

        # Test success on first attempt
        mock_session.active_window = mock_window
        mock_window.active_pane = mock_pane

        w, p = session._get_window_and_pane_with_retry(mock_session)
        assert w == mock_window
        assert p == mock_pane

        # Test retry logic
        mock_session.active_window = None
        with pytest.raises(RuntimeError, match="Window has no active pane"):
             with patch("time.sleep"):
                 session._get_window_and_pane_with_retry(mock_session, retries=2)

    def test_update_cwd(self, session):
        session._update_cwd("/new/path")
        assert session.cwd == "/new/path"

    def test_combine_outputs_no_matches(self, session):
        content = "some output"
        result = session._combine_outputs_between_matches(content, [])
        assert result == content

    def test_handle_previous_command_timeout(self, session):
        session.prev_status = BashCommandStatus.HARD_TIMEOUT
        CmdRunAction(command="ls")
        # If output doesn't end with PS1, it should return an observation
        with patch.object(session, "_get_pane_content", return_value="still running"):
             result = session._handle_previous_command_timeout("ls", "still running", [], False)
             assert result is not None
             assert "is NOT executed" in result.metadata.suffix

    def test_send_command_to_pane_special(self, session, mock_tmux):
        session._send_command_to_pane("C-c", is_input=True)
        # enter=False for special keys
        mock_tmux["pane"].send_keys.assert_called_with("C-c", enter=False)
