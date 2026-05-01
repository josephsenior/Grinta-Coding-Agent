from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.execution.drivers.local.local_runtime_inprocess import (
    LocalRuntimeInProcess,
)
from backend.core.constants import (
    CMD_PENDING_ACTION_TIMEOUT_FLOOR,
    TOOL_BRIDGE_TIMEOUT_BUFFER,
    TOOL_BRIDGE_TIMEOUT_DEBUGGER,
)
from backend.core.errors import AgentRuntimeDisconnectedError
from backend.ledger.action.browser_tool import BrowserToolAction
from backend.ledger.action.code_nav import LspQueryAction
from backend.ledger.action.debugger import DebuggerAction
from backend.ledger.action.terminal import (
    TerminalInputAction,
    TerminalReadAction,
    TerminalRunAction,
)
from backend.ledger.action import CmdRunAction
from backend.ledger.observation import NullObservation
from backend.ledger.observation.code_nav import LspQueryObservation
from backend.ledger.observation.commands import CmdOutputObservation


def _make_runtime() -> LocalRuntimeInProcess:
    with patch.object(LocalRuntimeInProcess, '_init_tooling_and_platform'):
        runtime = LocalRuntimeInProcess(
            config=MagicMock(),
            event_stream=MagicMock(),
            llm_registry=MagicMock(),
            sid='test-sid',
        )
    runtime._runtime_initialized = True
    return runtime


def test_terminal_run_forwards_to_runtime_executor() -> None:
    runtime = _make_runtime()
    obs = NullObservation(content='session-1')
    executor = MagicMock()
    executor.terminal_run = AsyncMock(return_value=obs)
    runtime._executor = executor
    action = TerminalRunAction(command='echo hi')
    result = runtime.terminal_run(action)
    assert result is obs
    executor.terminal_run.assert_awaited_once_with(action)


def test_terminal_input_forwards_to_runtime_executor() -> None:
    runtime = _make_runtime()
    obs = NullObservation(content='')
    executor = MagicMock()
    executor.terminal_input = AsyncMock(return_value=obs)
    runtime._executor = executor
    action = TerminalInputAction(session_id='s1', input='y')
    result = runtime.terminal_input(action)
    assert result is obs
    executor.terminal_input.assert_awaited_once_with(action)


def test_terminal_read_forwards_to_runtime_executor() -> None:
    runtime = _make_runtime()
    obs = NullObservation(content='out')
    executor = MagicMock()
    executor.terminal_read = AsyncMock(return_value=obs)
    runtime._executor = executor
    action = TerminalReadAction(session_id='s1')
    result = runtime.terminal_read(action)
    assert result is obs
    executor.terminal_read.assert_awaited_once_with(action)


def test_lsp_query_forwards_to_runtime_executor() -> None:
    runtime = _make_runtime()
    obs = LspQueryObservation(content='symbols', available=True)

    executor = MagicMock()
    executor.lsp_query = AsyncMock(return_value=obs)
    runtime._executor = executor

    action = LspQueryAction(command='list_symbols', file='sample.py')

    result = runtime.lsp_query(action)

    assert result is obs
    executor.lsp_query.assert_awaited_once_with(action)


def test_debugger_forwards_to_runtime_executor() -> None:
    runtime = _make_runtime()
    obs = NullObservation(content='debug')
    executor = MagicMock()
    executor.debugger = AsyncMock(return_value=obs)
    runtime._executor = executor
    action = DebuggerAction(debug_action='status', session_id='dbg-1')
    result = runtime.debugger(action)
    assert result is obs
    executor.debugger.assert_awaited_once_with(action)


def test_browser_tool_uses_persistent_loop_runner() -> None:
    runtime = _make_runtime()
    obs = CmdOutputObservation(
        content='Browser started.',
        command='browser start',
        metadata={'exit_code': 0},
    )
    executor = MagicMock()
    executor.browser_tool = AsyncMock(return_value=obs)
    runtime._executor = executor

    action = BrowserToolAction(command='start', params={})

    with patch(
        'backend.execution.drivers.local.local_runtime_inprocess._PersistentAsyncLoopRunner'
    ) as runner_cls:
        runner = MagicMock()
        runner.submit.return_value = obs
        runner_cls.return_value = runner

        result = runtime.browser_tool(action)
        assert result is obs
        runner.submit.assert_called_once_with(
            executor.browser_tool,
            300.0,
            action,
        )

        # Second call should reuse the same runner, not recreate it.
        runtime.browser_tool(action)
        runner_cls.assert_called_once()
        assert runner.submit.call_count == 2


def test_close_shuts_down_persistent_browser_runner() -> None:
    runtime = _make_runtime()
    runtime._executor = MagicMock()
    runner = MagicMock()
    runtime._browser_loop_runner = runner

    runtime.close()

    runner.close.assert_called_once()


def test_hard_kill_marks_runtime_uninitialized_and_drops_executor() -> None:
    runtime = _make_runtime()
    executor = MagicMock()
    executor.hard_kill = AsyncMock()
    runtime._executor = executor

    runtime.hard_kill()

    assert runtime.runtime_initialized is False
    assert runtime._executor is None
    executor.hard_kill.assert_awaited_once()


def test_run_after_hard_kill_requires_reconnect() -> None:
    from backend.ledger.action import CmdRunAction

    runtime = _make_runtime()
    runtime._executor = MagicMock()
    runtime.hard_kill()

    with pytest.raises(AgentRuntimeDisconnectedError, match='Runtime not initialized'):
        runtime.run(CmdRunAction(command='pwd'))


def test_cmd_run_bridge_timeout_aligns_with_default_cmd_floor() -> None:
    """Sync bridge must match CMD_PENDING_ACTION_TIMEOUT_FLOOR + buffer when unset."""
    runtime = _make_runtime()
    obs = CmdOutputObservation(content='ok', command='pwd', metadata={'exit_code': 0})
    executor = MagicMock()
    executor.run = AsyncMock(return_value=obs)
    runtime._executor = executor
    action = CmdRunAction(command='pwd')
    with patch(
        'backend.execution.drivers.local.local_runtime_inprocess.call_async_from_sync',
        return_value=obs,
    ) as call_sync:
        result = runtime.run(action)
    assert result is obs
    expected = float(CMD_PENDING_ACTION_TIMEOUT_FLOOR) + float(TOOL_BRIDGE_TIMEOUT_BUFFER)
    assert float(call_sync.call_args.args[1]) == pytest.approx(expected)


def test_debugger_bridge_timeout_respects_floor_when_action_timeout_is_small() -> None:
    runtime = _make_runtime()
    obs = NullObservation(content='debug')
    executor = MagicMock()
    executor.debugger = AsyncMock(return_value=obs)
    runtime._executor = executor
    action = DebuggerAction(debug_action='status', session_id='dbg-1', timeout=5)
    with patch(
        'backend.execution.drivers.local.local_runtime_inprocess.call_async_from_sync',
        return_value=obs,
    ) as call_sync:
        result = runtime.debugger(action)
    assert result is obs
    call_sync.assert_called_once()
    assert float(call_sync.call_args.args[1]) >= float(TOOL_BRIDGE_TIMEOUT_DEBUGGER)
