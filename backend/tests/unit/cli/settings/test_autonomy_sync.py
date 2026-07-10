from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from backend.cli.settings.query import (
    get_persisted_autonomy_level,
    sync_persisted_autonomy_to_controller,
)
from backend.engine.tools.param_defs import relax_security_risk_in_tools

_BALANCED_TOOL = {
    'type': 'function',
    'function': {
        'name': 'terminal',
        'parameters': {
            'type': 'object',
            'properties': {},
            'required': ['command', 'security_risk'],
        },
    },
}


@pytest.mark.parametrize('level', ['conservative', 'balanced', 'full'])
def test_sync_persisted_autonomy_applies_to_controller(level: str) -> None:
    controller = SimpleNamespace(
        autonomy_controller=SimpleNamespace(autonomy_level='balanced')
    )
    config = MagicMock()
    config.get_agent_config.return_value = SimpleNamespace(autonomy_level='balanced')

    with patch(
        'backend.cli.settings.query.get_persisted_autonomy_level',
        return_value=level,
    ):
        effective = sync_persisted_autonomy_to_controller(
            controller,
            'agent',
            config=config,
        )

    assert effective == level
    assert controller.autonomy_controller.autonomy_level == level
    assert config.autonomy_level == level
    assert config.get_agent_config.return_value.autonomy_level == level


def test_sync_persisted_autonomy_returns_runtime_when_not_persisted() -> None:
    controller = SimpleNamespace(
        autonomy_controller=SimpleNamespace(autonomy_level='full')
    )

    with patch(
        'backend.cli.settings.query.get_persisted_autonomy_level',
        return_value='',
    ):
        effective = sync_persisted_autonomy_to_controller(controller, 'agent')

    assert effective == 'full'
    assert controller.autonomy_controller.autonomy_level == 'full'


def test_sync_persisted_autonomy_rebuilds_toolset_for_full() -> None:
    planner = SimpleNamespace(
        _config=SimpleNamespace(mode='agent', autonomy_level='full'),
        build_toolset=MagicMock(
            side_effect=lambda: relax_security_risk_in_tools([_BALANCED_TOOL], 'full')
        ),
    )
    agent = SimpleNamespace(
        config=SimpleNamespace(mode='agent', autonomy_level='full'),
        planner=planner,
        tools=relax_security_risk_in_tools([_BALANCED_TOOL], 'balanced'),
    )
    controller = SimpleNamespace(
        autonomy_controller=SimpleNamespace(autonomy_level='balanced'),
        agent=agent,
    )

    with patch(
        'backend.cli.settings.query.get_persisted_autonomy_level',
        return_value='full',
    ):
        sync_persisted_autonomy_to_controller(controller, 'agent')

    required = agent.tools[0]['function']['parameters'].get('required', [])
    assert 'security_risk' not in required


def test_get_persisted_autonomy_rejects_supervised(tmp_path, monkeypatch) -> None:
    import backend.cli.settings.storage as storage_mod

    settings_path = tmp_path / 'settings.json'
    settings_path.write_text(
        json.dumps({'agent': {'agent': {'autonomy_level': 'supervised'}}}),
        encoding='utf-8',
    )
    monkeypatch.setattr(storage_mod, '_settings_path', lambda: settings_path)

    level = get_persisted_autonomy_level('agent')

    # Settings should be treated as invalid; no silent migration.
    assert level == ''

