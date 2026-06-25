"""Tests for interaction mode persistence in settings.json."""

from __future__ import annotations

import json
from pathlib import Path

from backend.cli.settings.query import (
    get_persisted_interaction_mode,
    update_interaction_mode,
)


def test_update_interaction_mode_persists_to_settings(
    tmp_path: Path, monkeypatch
) -> None:
    settings_path = tmp_path / 'settings.json'
    settings_path.write_text(
        json.dumps({'agent': {'Orchestrator': {'mode': 'agent'}}}),
        encoding='utf-8',
    )
    monkeypatch.setenv('APP_ROOT', str(tmp_path))

    update_interaction_mode('plan', 'Orchestrator')

    raw = json.loads(settings_path.read_text(encoding='utf-8'))
    assert raw['agent']['Orchestrator']['mode'] == 'plan'
    assert get_persisted_interaction_mode('Orchestrator') == 'plan'


def test_update_interaction_mode_rejects_invalid_mode(
    tmp_path: Path, monkeypatch
) -> None:
    settings_path = tmp_path / 'settings.json'
    settings_path.write_text(
        json.dumps({'agent': {'Orchestrator': {'mode': 'agent'}}}),
        encoding='utf-8',
    )
    monkeypatch.setenv('APP_ROOT', str(tmp_path))

    update_interaction_mode('invalid-mode', 'Orchestrator')

    raw = json.loads(settings_path.read_text(encoding='utf-8'))
    assert raw['agent']['Orchestrator']['mode'] == 'agent'
