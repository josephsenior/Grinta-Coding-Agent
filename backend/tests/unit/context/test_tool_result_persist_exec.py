"""Tests for execution-time tool result persistence."""

from __future__ import annotations

from unittest.mock import MagicMock

from backend.context.tool_result_storage import (
    TOOL_RESULT_REPLACEMENTS_KEY,
    apply_frozen_tool_replacements,
    persist_tool_result_on_observation,
)
from backend.ledger.observation.commands import CmdOutputObservation


def test_persist_tool_result_on_observation_stores_frozen_preview(tmp_path, monkeypatch):
    monkeypatch.setattr(
        'backend.context.tool_result_storage._tool_results_dir',
        lambda: tmp_path,
    )
    state = MagicMock()
    state.extra_data = {}

    def _set_extra(key, value, source='test'):
        state.extra_data[key] = value

    state.set_extra = _set_extra

    content = 'x' * 25_000
    obs = CmdOutputObservation(
        content=content,
        command='cat big.log',
        metadata={},
        hidden=True,
    )
    obs.id = 42

    persist_tool_result_on_observation(obs, state)
    replacements = state.extra_data.get(TOOL_RESULT_REPLACEMENTS_KEY, {})
    assert '42' in replacements
    assert 'persisted-output' in replacements['42'].lower() or 'saved to' in replacements['42'].lower()

    copied = CmdOutputObservation(
        content=content,
        command='cat big.log',
        metadata={},
        hidden=True,
    )
    copied.id = 42
    result = apply_frozen_tool_replacements([copied], state)
    assert str(getattr(result[0], 'content', '')) == replacements['42']
