from __future__ import annotations

import pathlib
from typing import TYPE_CHECKING, cast
from unittest.mock import MagicMock, patch

import pytest

from backend.execution.utils.simple_bash import SimpleBashSession
from backend.ledger.action import CmdRunAction
from backend.ledger.observation import ErrorObservation
from backend.ledger.observation.commands import CmdOutputObservation

if TYPE_CHECKING:
    from backend.execution.utils.process_registry import TaskCancellationService
    from backend.ledger.observation.commands import CmdOutputObservation


class TestSimpleBashSession:
    @pytest.fixture
    def mock_cancellation(self) -> MagicMock:
        return MagicMock()

    @pytest.fixture
    def session(
        self, tmp_path: pathlib.Path, mock_cancellation: MagicMock
    ) -> SimpleBashSession:
        # Use a sub-path that doesn't exist to trigger makedirs
        work_dir = tmp_path / 'new_bash_dir'
        s = SimpleBashSession(
            work_dir=str(work_dir), cancellation_service=cast('TaskCancellationService', mock_cancellation)
        )
        s.initialize()
        return s

    def test_initialize_new_dir(
        self, tmp_path: pathlib.Path, mock_cancellation: MagicMock
    ) -> None:
        """Covers lines 42-43."""
        work_dir = tmp_path / 'sub' / 'new'
        assert not work_dir.exists()
        s = SimpleBashSession(
            work_dir=str(work_dir), cancellation_service=cast('TaskCancellationService', mock_cancellation)
        )
        s.initialize()
        assert work_dir.exists()

    def test_execute_uninitialized(
        self, tmp_path: pathlib.Path, mock_cancellation: MagicMock
    ) -> None:
        s = SimpleBashSession(
            work_dir=str(tmp_path), cancellation_service=cast('TaskCancellationService', mock_cancellation)
        )
        action = CmdRunAction(command='ls')
        result = s.execute(action)
        assert isinstance(result, ErrorObservation)
        assert 'not initialized' in result.content

    def test_execute_interactive_input_error(self, session: SimpleBashSession) -> None:
        action = CmdRunAction(command='some input', is_input=True)
        action.set_hard_timeout(10.0)
        result = session.execute(action)
        assert isinstance(result, ErrorObservation)
        assert 'Interactive input not supported' in result.content

    @patch('backend.execution.utils.simple_bash.bounded_communicate')
    @patch('subprocess.Popen')
    def test_execute_command_success(
        self, mock_popen: MagicMock, mock_bc: MagicMock, session: SimpleBashSession
    ) -> None:
        from backend.execution.utils.bounded_io import BoundedResult

        mock_popen.return_value = MagicMock(pid=1234)
        mock_bc.return_value = BoundedResult(
            stdout='stdout_val',
            stderr='',
            returncode=0,
            truncated=False,
            timed_out=False,
        )

        action = CmdRunAction(command='echo hello')
        action.set_hard_timeout(10.0)
        result = session.execute(action)

        assert isinstance(result, CmdOutputObservation)
        assert result.content == 'stdout_val'

    @patch('backend.execution.utils.simple_bash.bounded_communicate')
    @patch('subprocess.Popen')
    def test_execute_command_with_cd(
        self, mock_popen: MagicMock, mock_bc: MagicMock, session: SimpleBashSession
    ) -> None:
        """Covers lines 123, 150."""
        from backend.execution.utils.bounded_io import BoundedResult

        mock_popen.return_value = MagicMock(pid=1234)
        mock_bc.return_value = BoundedResult(
            stdout='/new/path',
            stderr='',
            returncode=0,
            truncated=False,
            timed_out=False,
        )

        action = CmdRunAction(command='cd /new/path')
        action.set_hard_timeout(10.0)
        session.execute(action)
        # cd triggers a follow-up `pwd` via subprocess.run inside
        # _update_cwd_from_output, so Popen runs at least once for the
        # original command.
        assert mock_popen.call_count >= 1

    @patch('backend.execution.utils.simple_bash.bounded_communicate')
    @patch('subprocess.Popen')
    def test_execute_background_failure_fallback(
        self, mock_popen: MagicMock, mock_bc: MagicMock, session: SimpleBashSession
    ) -> None:
        """Covers lines 103-106."""
        from backend.execution.utils.bounded_io import BoundedResult

        mock_popen.return_value = MagicMock(pid=1234)
        # First call (nohup) returns non-digit, second (fallback) returns text
        mock_bc.side_effect = [
            BoundedResult(
                stdout='error\n', stderr='', returncode=0,
                truncated=False, timed_out=False,
            ),
            BoundedResult(
                stdout='stdout\n', stderr='', returncode=0,
                truncated=False, timed_out=False,
            ),
        ]

        action = CmdRunAction(command='sleep 100 &')
        action.set_hard_timeout(10.0)
        result = session.execute(action)
        assert isinstance(result, CmdOutputObservation)
        assert result.content == 'stdout'

    @patch('backend.execution.utils.simple_bash.bounded_communicate')
    @patch('subprocess.Popen')
    def test_execute_background_registration_exception(
        self, mock_popen: MagicMock, mock_bc: MagicMock, session: SimpleBashSession
    ) -> None:
        """Covers lines 93-94."""
        from backend.execution.utils.bounded_io import BoundedResult

        mock_popen.return_value = MagicMock(pid=1234)
        mock_bc.return_value = BoundedResult(
            stdout='123\n', stderr='', returncode=0,
            truncated=False, timed_out=False,
        )

        # Mock register_pid to fail
        # session._cancellation is TaskCancellationService
        cast(MagicMock, session._cancellation.register_pid).side_effect = Exception('Reg fail')

        action = CmdRunAction(command='sleep 100 &')
        action.set_hard_timeout(10.0)
        result = session.execute(action)
        assert isinstance(result, CmdOutputObservation)
        assert '[123]' in result.content

    def test_run_command_closed_error(self, session: SimpleBashSession) -> None:
        """Covers line 115."""
        session.close()
        with pytest.raises(RuntimeError, match='closed'):
            session._run_command('ls')

    @patch('backend.execution.utils.simple_bash.bounded_communicate')
    @patch('subprocess.Popen')
    def test_handle_subprocess_timeout(
        self, mock_popen: MagicMock, mock_bc: MagicMock, session: SimpleBashSession
    ) -> None:
        from backend.execution.utils.bounded_io import BoundedResult

        mock_popen.return_value = MagicMock(pid=1234)
        mock_bc.return_value = BoundedResult(
            stdout='', stderr='', returncode=124,
            truncated=False, timed_out=True,
        )

        action = CmdRunAction(command='ls')
        action.set_hard_timeout(10.0)
        result = session.execute(action)
        assert isinstance(result, CmdOutputObservation)
        assert 'timed out' in result.content
