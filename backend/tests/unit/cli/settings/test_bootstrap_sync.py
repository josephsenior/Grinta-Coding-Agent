"""Tests for bootstrap_sync.sync_controller_persisted_settings."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from backend.cli.settings.bootstrap_sync import sync_controller_persisted_settings


def test_sync_controller_persisted_settings_applies_mode_and_autonomy() -> None:
    controller = MagicMock()
    hud = MagicMock()

    with (
        patch(
            'backend.cli.settings.sync_persisted_interaction_mode_to_controller',
            return_value='plan',
        ) as mode_sync,
        patch(
            'backend.cli.settings.sync_persisted_autonomy_to_controller',
            return_value='conservative',
        ) as autonomy_sync,
    ):
        sync_controller_persisted_settings(
            controller,
            'Orchestrator',
            config=MagicMock(),
            hud=hud,
        )

    mode_sync.assert_called_once()
    autonomy_sync.assert_called_once()
    hud.update_interaction_mode.assert_called_once_with('plan')
    hud.update_autonomy.assert_called_once_with('conservative')
