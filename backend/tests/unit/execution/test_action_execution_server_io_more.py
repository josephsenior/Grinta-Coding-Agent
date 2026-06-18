from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.execution.action_execution_server import RuntimeExecutor
from backend.execution.utils.shell.unified_shell import BaseShellSession
from backend.ledger.action import (
    CmdRunAction,
    FileEditAction,
    FileReadAction,
)
from backend.ledger.observation import (
    CmdOutputObservation,
    ErrorObservation,
    FileReadObservation,
)


@pytest.fixture
def mock_executor(tmp_path: Path):
    with (
        patch('os.makedirs'),
        patch('backend.execution.action_execution_server.SessionManager'),
    ):
        executor = RuntimeExecutor(
            plugins_to_load=[],
            work_dir=str(tmp_path / 'workspace'),
            username='testuser',
            user_id=1000,
            enable_browser=False,
            security_config=SimpleNamespace(execution_profile='standard'),
        )
        executor.session_manager = MagicMock()
        executor.plugins = {}
        return executor


class _Obs:
    def __init__(self) -> None:
        self.content = '\x1b[31mhello\x1b[0m'
        self.path = '\x1b[32m/tmp/a\x1b[0m'
        self._msg = 'x'

    @property
    def message(self) -> str:
        return self._msg

    @message.setter
    def message(self, value: str) -> None:
        raise AttributeError('immutable')


@pytest.mark.asyncio
async def test_run_action_strips_ansi_and_tolerates_message_setter_error(
    mock_executor,
) -> None:
    action = SimpleNamespace(action='dummy')
    mock_executor.dummy = AsyncMock(return_value=_Obs())
    obs = await mock_executor.run_action(action)
    assert obs.content == 'hello'
    assert obs.path == '/tmp/a'


@pytest.mark.asyncio
async def test_run_foreground_recreates_default_session_when_missing(
    mock_executor,
) -> None:
    recreated = MagicMock(spec=BaseShellSession)
    recreated.execute.return_value = CmdOutputObservation(
        content='C:/ws',
        command='pwd',
        metadata={'exit_code': 0},
    )
    mock_executor.session_manager.get_session.return_value = None
    mock_executor.session_manager.create_session.return_value = recreated

    out = await mock_executor._run_foreground_cmd(CmdRunAction(command='pwd'))

    assert isinstance(out, CmdOutputObservation)
    assert out.content == 'C:/ws'
    mock_executor.session_manager.create_session.assert_called_once_with(
        session_id='default'
    )


@pytest.mark.asyncio
async def test_read_returns_error_when_default_session_recreation_fails(
    mock_executor,
) -> None:
    mock_executor.session_manager.get_session.return_value = None
    mock_executor.session_manager.create_session.side_effect = RuntimeError('boom')

    out = await mock_executor.read(FileReadAction(path='foo.txt'))

    assert isinstance(out, ErrorObservation)
    assert 'recreation failed' in out.content


@pytest.mark.asyncio
async def test_run_foreground_returns_error_for_non_shell_default_session(
    mock_executor,
) -> None:
    mock_executor.session_manager.get_session.return_value = object()
    out = await mock_executor._run_foreground_cmd(CmdRunAction(command='pwd'))
    assert isinstance(out, ErrorObservation)
    assert 'not a foreground shell' in out.content


@pytest.mark.asyncio
async def test_run_static_closes_temp_session_even_on_success(mock_executor) -> None:
    session = MagicMock(spec=BaseShellSession)
    session.execute.return_value = SimpleNamespace(content='ok', command='ls')
    mock_executor.session_manager.create_session.return_value = session
    mock_executor.session_manager.get_session.return_value = MagicMock(cwd='C:/ws')

    out = await mock_executor._run_static_cmd(
        CmdRunAction(command='ls', is_static=True)
    )
    assert out.content == 'ok'
    mock_executor.session_manager.close_session.assert_called_once()


@pytest.mark.asyncio
async def test_read_binary_file_returns_binary_error(mock_executor) -> None:
    session = MagicMock(spec=BaseShellSession)
    session.cwd = 'C:/ws'
    mock_executor.session_manager.get_session.return_value = session
    with (
        patch('os.path.isfile', return_value=True),
        patch(
            'backend.execution.io_mixins._aes_io_file_mixin.is_binary',
            return_value=True,
        ),
    ):
        out = await mock_executor.read(FileReadAction(path='foo.bin'))
    assert isinstance(out, ErrorObservation)
    assert out.content == 'ERROR_BINARY_FILE'


@pytest.mark.asyncio
async def test_read_file_editor_source_uses_aci_handler(mock_executor) -> None:
    session = MagicMock(spec=BaseShellSession)
    session.cwd = 'C:/ws'
    mock_executor.session_manager.get_session.return_value = session
    expected = FileReadObservation(path='x.py', content='ok')
    with patch.object(mock_executor, '_handle_aci_file_read', return_value=expected):
        out = await mock_executor.read(
            FileReadAction(path='x.py', impl_source='file_editor')  # type: ignore[arg-type]
        )
    assert out is expected


@pytest.mark.asyncio
async def test_read_workspace_permission_error_returns_guidance(mock_executor) -> None:
    session = MagicMock(spec=BaseShellSession)
    session.cwd = 'C:/ws'
    mock_executor.session_manager.get_session.return_value = session
    with patch.object(
        mock_executor, '_resolve_workspace_file_path', side_effect=PermissionError()
    ):
        out = await mock_executor.read(FileReadAction(path='../secret.txt'))
    assert isinstance(out, ErrorObservation)
    assert 'only access paths inside the workspace' in out.content


@pytest.mark.asyncio
async def test_read_dispatches_by_extension(mock_executor) -> None:
    session = MagicMock(spec=BaseShellSession)
    session.cwd = 'C:/ws'
    mock_executor.session_manager.get_session.return_value = session
    with (
        patch.object(
            mock_executor, '_resolve_workspace_file_path', return_value='C:/ws/a.png'
        ),
        patch(
            'backend.execution.io_mixins._aes_io_file_mixin.read_image_file',
            return_value=FileReadObservation(path='a.png', content='img'),
        ) as img,
    ):
        out = await mock_executor.read(FileReadAction(path='a.png'))
    assert isinstance(out, FileReadObservation)
    img.assert_called_once()


@pytest.mark.asyncio
async def test_edit_create_permission_error_path(mock_executor) -> None:
    session = MagicMock(spec=BaseShellSession)
    session.cwd = 'C:/ws'
    mock_executor.session_manager.get_session.return_value = session
    with patch.object(
        mock_executor,
        '_resolve_workspace_file_path',
        side_effect=PermissionError('nope'),
    ):
        out = await mock_executor.edit(
            FileEditAction(path='../a.txt', command='create_file', file_text='x')
        )
    assert isinstance(out, ErrorObservation)
    assert 'not allowed to access this path' in out.content


@pytest.mark.asyncio
async def test_edit_create_success_path(mock_executor) -> None:
    from backend.ledger.observation import FileEditObservation

    session = MagicMock(spec=BaseShellSession)
    session.cwd = 'C:/ws'
    mock_executor.session_manager.get_session.return_value = session
    expected = FileEditObservation(
        content='File created successfully.',
        path='a.txt',
        outcome='created',
        new_content='x',
    )
    with patch.object(
        mock_executor, '_edit_via_file_editor', return_value=expected
    ) as mock_edit:
        out = await mock_executor.edit(
            FileEditAction(path='a.txt', command='create_file', file_text='x')
        )
    assert isinstance(out, FileEditObservation)
    mock_edit.assert_called_once()
    edit_action = mock_edit.call_args[0][0]
    assert edit_action.command == 'create_file'
    assert edit_action.file_text == 'x'


@pytest.mark.asyncio
async def test_edit_permission_error_command_missing_and_directory_view(
    mock_executor,
) -> None:
    session = MagicMock(spec=BaseShellSession)
    session.cwd = 'C:/ws'
    mock_executor.session_manager.get_session.return_value = session
    with patch.object(
        mock_executor, '_resolve_workspace_file_path', side_effect=PermissionError()
    ):
        out1 = await mock_executor.edit(FileEditAction(path='../x', command='replace'))
    assert isinstance(out1, ErrorObservation)

    with (
        patch.object(
            mock_executor, '_resolve_workspace_file_path', return_value='C:/ws/x'
        ),
        patch.object(mock_executor, '_edit_try_directory_view', return_value=None),
    ):
        out2 = await mock_executor.edit(FileEditAction(path='x', command=''))
    assert isinstance(out2, ErrorObservation)
    assert 'no longer supported' in out2.content

    directory_obs = FileReadObservation(path='x', content='[DIR]')
    with (
        patch.object(
            mock_executor, '_resolve_workspace_file_path', return_value='C:/ws/x'
        ),
        patch.object(
            mock_executor, '_edit_try_directory_view', return_value=directory_obs
        ),
    ):
        out3 = await mock_executor.edit(FileEditAction(path='x', command='replace'))
    assert out3 is directory_obs
