from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from backend.execution.drivers.local.local_runtime_inprocess import (
    LocalRuntimeInProcess,
)
from backend.ledger.action.browser_tool import BrowserToolAction
from backend.ledger.action.code_nav import LspQueryAction
from backend.ledger.observation.commands import CmdOutputObservation
from backend.ledger.observation.code_nav import LspQueryObservation


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
            165.0,
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
