"""Tests for background turn sync and terminal wait/list helpers."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from backend.execution.server.action_execution_server import RuntimeExecutor
from backend.execution.utils.shell.background_turn_sync import (
    apply_background_drain_to_state,
    cap_background_output,
    sync_background_output_for_turn,
)
from backend.ledger.action.terminal import TerminalListAction, TerminalWaitAction


@pytest.fixture
def mock_executor(tmp_path: Path):
    with (
        patch('os.makedirs'),
        patch('backend.execution.server.action_execution_server.SessionManager'),
    ):
        executor = RuntimeExecutor(
            plugins_to_load=[],
            work_dir=str(tmp_path / 'test'),
            username='testuser',
            user_id=1000,
            enable_browser=False,
            security_config=SimpleNamespace(execution_profile='standard'),
        )
        executor.session_manager = MagicMock()
        executor.plugins = {}
        executor._terminal_read_cursor = {}
        executor._terminal_empty_read_streak = {}
        return executor


def test_cap_background_output_limits_lines_and_chars() -> None:
    text = '\n'.join(f'line-{i}' for i in range(50))
    capped = cap_background_output(text, max_lines=5, max_chars=80)
    assert 'line-49' in capped
    assert len(capped) <= 120


def test_sync_background_output_for_turn_drains_live_sessions() -> None:
    session = SimpleNamespace(_process=SimpleNamespace(poll=lambda: None), cwd='/tmp')
    session_manager = SimpleNamespace(
        sessions={'default': object(), 'bg-abc12345': session}
    )
    executor = MagicMock()
    executor.session_manager = session_manager
    executor._terminal_read_cursor = {}

    from backend.execution.aes import helpers as aes_helpers

    original = aes_helpers.read_terminal_with_mode

    def _fake_read(_executor, *, session, mode, offset):
        assert mode == 'delta'
        return ('Server ready on http://localhost:5173\n', 42, True, None)

    aes_helpers.read_terminal_with_mode = _fake_read
    try:
        drains = sync_background_output_for_turn(executor)
    finally:
        aes_helpers.read_terminal_with_mode = original

    assert drains == {'bg-abc12345': 'Server ready on http://localhost:5173'}
    assert executor._terminal_read_cursor['bg-abc12345'] == 42


def test_apply_background_drain_to_state_updates_canonical_task() -> None:
    from backend.context.canonical_state import (
        load_canonical_state,
        save_canonical_state,
    )
    from backend.context.canonical_state.types import (
        BackgroundTaskState,
        CanonicalTaskState,
    )
    from backend.orchestration.state.state import State

    state = State(session_id='test-session')
    canonical = CanonicalTaskState(
        background_tasks=[
            BackgroundTaskState(
                session_id='bg-abc12345',
                command='npm run dev',
                status='still running',
            )
        ]
    )
    save_canonical_state(canonical, state=state)

    apply_background_drain_to_state(
        state,
        {'bg-abc12345': 'listening on http://localhost:5173'},
    )

    updated = load_canonical_state(state=state)
    assert updated.background_tasks[0].recent_output.startswith('listening on')


@pytest.mark.asyncio
async def test_terminal_wait_matches_pattern(mock_executor):
    session = SimpleNamespace(
        _process=SimpleNamespace(poll=lambda: None),
        cwd='/tmp',
    )
    calls = {'n': 0}

    def read_output_since(offset: int):
        calls['n'] += 1
        if calls['n'] == 1:
            return ('starting...\n', 20, None)
        return ('listening on http://localhost:5173\n', 60, None)

    session.read_output_since = read_output_since
    mock_executor.session_manager.get_session.return_value = session
    mock_executor._validate_interactive_session_scope = lambda *_a, **_k: None
    mock_executor._mark_terminal_session_interaction = MagicMock()

    obs = await mock_executor.terminal_wait(
        TerminalWaitAction(
            session_id='bg-abc12345',
            pattern='listening on',
            timeout=5,
        )
    )

    assert 'listening on' in obs.content
    assert obs.tool_result['payload']['matched'] is True


@pytest.mark.asyncio
async def test_terminal_list_reports_sessions(mock_executor):
    session = SimpleNamespace(
        _process=SimpleNamespace(poll=lambda: None),
        cwd='/project',
    )
    mock_executor.session_manager.sessions = {
        'default': object(),
        'bg-abc12345': session,
    }

    obs = await mock_executor.terminal_list(TerminalListAction())
    assert 'bg-abc12345' in obs.content
    assert obs.tool_result['payload']['sessions'][0]['session_id'] == 'bg-abc12345'
