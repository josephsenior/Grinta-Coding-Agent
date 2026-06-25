"""Tests for sync_persisted_interaction_mode_to_controller."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from backend.cli.settings.query import sync_persisted_interaction_mode_to_controller


def test_sync_persisted_interaction_mode_applies_plan_mode() -> None:
    controller = MagicMock()
    agent = MagicMock()
    agent.config = MagicMock(mode='agent')
    controller.agent = agent

    with (
        patch(
            'backend.cli.settings.query.get_persisted_interaction_mode',
            return_value='plan',
        ),
        patch(
            'backend.cli.settings.mode_runtime.apply_interaction_mode_to_controller',
        ) as apply_mock,
    ):
        mode = sync_persisted_interaction_mode_to_controller(
            controller,
            'Orchestrator',
            config=MagicMock(),
        )

    assert mode == 'plan'
    apply_mock.assert_called_once_with(controller, 'plan')
