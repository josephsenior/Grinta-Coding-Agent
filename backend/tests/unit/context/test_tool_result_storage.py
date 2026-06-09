"""Tests for tool-result persistence and prompt budgets."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from backend.context.tool_result_storage import (
    apply_tool_result_budget,
    extract_latest_pytest_summary,
    persist_tool_output,
)
from backend.ledger.action import CmdRunAction
from backend.ledger.observation.commands import CmdOutputObservation
from backend.ledger.observation.terminal import TerminalObservation


def _cmd_output(event_id: int, content: str, *, exit_code: int = 0) -> CmdOutputObservation:
    obs = CmdOutputObservation(content=content, command='pytest -q', exit_code=exit_code)
    obs.id = event_id
    return obs


def test_persist_tool_output_writes_preview(tmp_path: Path) -> None:
    obs = _cmd_output(1, 'x' * 20_000)
    with patch(
        'backend.context.tool_result_storage._tool_results_dir',
        return_value=tmp_path,
    ):
        filepath, preview = persist_tool_output(obs.content, obs)

    assert Path(filepath).exists()
    assert 'persisted-output' in preview
    assert 'Original size:' in preview


def test_apply_tool_result_budget_persists_large_observation(tmp_path: Path) -> None:
    huge = 'line\n' * 8_000
    events = [
        CmdRunAction(command='pytest -q'),
        _cmd_output(2, huge),
    ]
    events[0].id = 1
    with patch(
        'backend.context.tool_result_storage._tool_results_dir',
        return_value=tmp_path,
    ):
        result = apply_tool_result_budget(events, persist_threshold=1000)

    assert result[0] is events[0]
    assert result[1] is not events[1]
    assert 'persisted-output' in str(result[1].content)


def test_apply_tool_result_budget_persists_terminal_observation(tmp_path: Path) -> None:
    huge = 'terminal line\n' * 8_000
    obs = TerminalObservation(session_id='term-1', content=huge)
    obs.id = 5
    with patch(
        'backend.context.tool_result_storage._tool_results_dir',
        return_value=tmp_path,
    ):
        result = apply_tool_result_budget([obs], persist_threshold=1000)

    assert result[0] is not obs
    assert 'persisted-output' in str(result[0].content)


def test_extract_latest_pytest_summary() -> None:
    events = [
        _cmd_output(1, '============================= 2 passed in 1.0s ============================='),
        _cmd_output(3, '======================== 18 failed, 9 passed in 50.31s ========================'),
    ]
    assert extract_latest_pytest_summary(events) == '18 failed, 9 passed in 50.31s'
