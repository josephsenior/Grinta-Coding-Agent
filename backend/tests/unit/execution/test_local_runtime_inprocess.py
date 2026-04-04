from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from backend.execution.drivers.local.local_runtime_inprocess import (
    LocalRuntimeInProcess,
)
from backend.ledger.action.code_nav import LspQueryAction
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
