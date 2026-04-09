"""Unit tests for backend.engine.tools.revert_to_checkpoint."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import backend.core.workspace_resolution as workspace_resolution
from backend.engine.tools import revert_to_checkpoint


def _extract_payload(thought: str) -> dict:
    marker = '[REVERT_RESULT] '
    assert marker in thought
    return json.loads(thought.split(marker, 1)[1])


class _FakeRollbackManager:
    def __init__(self, latest=None, rollback_ok=True):
        self._latest = latest
        self._rollback_ok = rollback_ok
        self.rollback_calls: list[str] = []

    def get_latest_checkpoint(self):
        return self._latest

    def get_checkpoint(self, checkpoint_id: str):
        if checkpoint_id == 'cp_existing':
            return SimpleNamespace(id=checkpoint_id)
        return None

    def rollback_to(self, checkpoint_id: str) -> bool:
        self.rollback_calls.append(checkpoint_id)
        return self._rollback_ok


def test_revert_to_checkpoint_no_checkpoints_returns_structured_payload(
    monkeypatch, tmp_path: Path
) -> None:
    manager = _FakeRollbackManager(latest=None)
    monkeypatch.setattr(revert_to_checkpoint, 'RollbackManager', lambda **_: manager)
    monkeypatch.setattr(
        workspace_resolution,
        'require_effective_workspace_root',
        lambda: tmp_path,
    )

    action = revert_to_checkpoint.build_revert_to_checkpoint_action({})

    payload = _extract_payload(action.thought)
    assert payload['tool'] == 'revert_to_checkpoint'
    assert payload['ok'] is False
    assert payload['reason_code'] == 'NO_CHECKPOINTS'
    assert action.tool_result == payload


def test_revert_to_checkpoint_success_returns_structured_payload(
    monkeypatch, tmp_path: Path
) -> None:
    manager = _FakeRollbackManager(latest=SimpleNamespace(id='cp_latest'))
    monkeypatch.setattr(revert_to_checkpoint, 'RollbackManager', lambda **_: manager)
    monkeypatch.setattr(
        workspace_resolution,
        'require_effective_workspace_root',
        lambda: tmp_path,
    )
    monkeypatch.setattr(
        revert_to_checkpoint,
        '_resolve_rollback_id',
        lambda checkpoint_id, manager: 'cp_existing',
    )

    action = revert_to_checkpoint.build_revert_to_checkpoint_action(
        {'checkpoint_id': '12'}
    )

    payload = _extract_payload(action.thought)
    assert payload['tool'] == 'revert_to_checkpoint'
    assert payload['ok'] is True
    assert payload['status'] == 'reverted'
    assert payload['reason_code'] == 'ROLLBACK_COMPLETED'
    assert payload['data']['requested_checkpoint_id'] == '12'
    assert payload['data']['resolved_checkpoint_id'] == 'cp_existing'
    assert manager.rollback_calls == ['cp_existing']
    assert action.tool_result == payload
