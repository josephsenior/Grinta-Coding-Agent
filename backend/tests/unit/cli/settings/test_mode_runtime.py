"""Tests for interaction-mode runtime helpers."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from backend.cli.settings.mode_runtime import (
    apply_interaction_mode_to_controller,
    rebuild_agent_toolset,
)


def test_rebuild_agent_toolset_refreshes_tools() -> None:
    planner = SimpleNamespace(_config=SimpleNamespace(mode='agent'), build_toolset=MagicMock(return_value=['read']))
    agent = SimpleNamespace(config=SimpleNamespace(mode='agent'), planner=planner, tools=[])

    rebuild_agent_toolset(agent, mode='plan')

    assert agent.config.mode == 'plan'
    assert planner._config.mode == 'plan'
    assert agent.tools == ['read']


def test_apply_interaction_mode_to_controller_updates_extra_data() -> None:
    planner = SimpleNamespace(_config=SimpleNamespace(mode='agent'), build_toolset=MagicMock(return_value=[]))
    agent = SimpleNamespace(config=SimpleNamespace(mode='agent'), planner=planner, tools=[])
    controller = SimpleNamespace(agent=agent, state=SimpleNamespace(extra_data={}))

    apply_interaction_mode_to_controller(controller, 'plan')

    assert controller.state.extra_data['active_run_mode'] == 'plan'
