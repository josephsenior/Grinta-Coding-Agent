"""Tests for interaction-mode runtime helpers."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from backend.cli.settings.mode_runtime import (
    apply_autonomy_to_controller,
    apply_interaction_mode_to_controller,
    rebuild_agent_toolset,
)
from backend.engine.contracts import ChatCompletionToolParam
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


def _toolset_for_autonomy(level: str) -> list[ChatCompletionToolParam]:
    return relax_security_risk_in_tools([_BALANCED_TOOL], level)  # type: ignore[arg-type]


def test_rebuild_agent_toolset_refreshes_tools() -> None:
    planner = SimpleNamespace(
        _config=SimpleNamespace(mode='agent'),
        build_toolset=MagicMock(return_value=['read']),
    )
    agent = SimpleNamespace(
        config=SimpleNamespace(mode='agent'), planner=planner, tools=[]
    )

    rebuild_agent_toolset(agent, mode='plan')

    assert agent.config.mode == 'plan'
    assert planner._config.mode == 'plan'
    assert agent.tools == ['read']


def test_apply_interaction_mode_to_controller_updates_extra_data() -> None:
    planner = SimpleNamespace(
        _config=SimpleNamespace(mode='agent'), build_toolset=MagicMock(return_value=[])
    )
    agent = SimpleNamespace(
        config=SimpleNamespace(mode='agent'), planner=planner, tools=[]
    )
    controller = SimpleNamespace(agent=agent, state=SimpleNamespace(extra_data={}))

    apply_interaction_mode_to_controller(controller, 'plan')

    assert controller.state.extra_data['active_run_mode'] == 'plan'


def test_apply_autonomy_to_controller_rebuilds_security_risk_schema() -> None:
    planner = SimpleNamespace(
        _config=SimpleNamespace(mode='agent', autonomy_level='balanced'),
        build_toolset=MagicMock(side_effect=lambda: _toolset_for_autonomy('full')),
    )
    agent = SimpleNamespace(
        config=SimpleNamespace(mode='agent', autonomy_level='full'),
        planner=planner,
        tools=_toolset_for_autonomy('balanced'),
    )
    controller = SimpleNamespace(agent=agent)

    apply_autonomy_to_controller(controller)

    required = agent.tools[0]['function']['parameters'].get('required', [])
    assert 'security_risk' not in required


def test_apply_autonomy_to_controller_syncs_from_ac_when_config_stale() -> None:
    """Toolset rebuild must use AutonomyController, not stale agent.config."""
    agent_config = SimpleNamespace(mode='agent', autonomy_level='balanced')
    planner = SimpleNamespace(_config=agent_config, build_toolset=MagicMock())
    agent = SimpleNamespace(
        config=agent_config,
        planner=planner,
        tools=_toolset_for_autonomy('balanced'),
    )
    planner.build_toolset.side_effect = lambda: _toolset_for_autonomy(
        agent.config.autonomy_level
    )
    controller = SimpleNamespace(
        agent=agent,
        autonomy_controller=SimpleNamespace(autonomy_level='full'),
    )

    apply_autonomy_to_controller(controller)

    assert agent.config.autonomy_level == 'full'
    required = agent.tools[0]['function']['parameters'].get('required', [])
    assert 'security_risk' not in required

