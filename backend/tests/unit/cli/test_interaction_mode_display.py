"""Tests for get_current_interaction_mode active_run_mode resolution."""

from __future__ import annotations

from unittest.mock import MagicMock

from backend.cli.repl.slash_command_status import get_current_interaction_mode


def test_get_current_interaction_mode_prefers_active_run_mode() -> None:
    host = MagicMock()
    controller = MagicMock()
    agent = MagicMock()
    agent.config = MagicMock(mode='agent')
    controller.agent = agent
    controller.state = MagicMock(extra_data={'active_run_mode': 'plan'})
    host._controller = controller
    host._config = None

    assert get_current_interaction_mode(host) == 'plan'


def test_get_current_interaction_mode_falls_back_to_configured_mode() -> None:
    host = MagicMock()
    controller = MagicMock()
    agent = MagicMock()
    agent.config = MagicMock(mode='chat')
    controller.agent = agent
    controller.state = MagicMock(extra_data={})
    host._controller = controller
    host._config = None

    assert get_current_interaction_mode(host) == 'chat'
