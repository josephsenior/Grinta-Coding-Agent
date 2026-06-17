from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from backend.cli.settings.query import sync_persisted_autonomy_to_controller


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
