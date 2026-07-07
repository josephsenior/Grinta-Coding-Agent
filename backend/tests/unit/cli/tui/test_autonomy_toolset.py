"""Regression tests for TUI autonomy hot-switch tool schema updates."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from backend.cli.tui.screen.settings import ScreenSettingsMixin
from backend.engine.tools.param_defs import relax_security_risk_in_tools


_BALANCED_TOOL = {
    'type': 'function',
    'function': {
        'name': 'execute_bash',
        'parameters': {
            'type': 'object',
            'properties': {},
            'required': ['command', 'security_risk'],
        },
    },
}


def _toolset_for_autonomy(level: str) -> list[dict]:
    return relax_security_risk_in_tools([_BALANCED_TOOL], level)


class _AutonomyScreenStub(ScreenSettingsMixin):
    """Minimal host for ``_apply_autonomy_level`` without Textual."""

    def __init__(self) -> None:
        self._hud_autonomy_syncing = False
        self._config = SimpleNamespace(default_agent='agent')
        self._hud = SimpleNamespace(
            state=SimpleNamespace(autonomy_level='balanced'),
            update_autonomy=MagicMock(),
        )
        self._renderer = None
        self.notify = MagicMock()

    def _visible_autonomy_level(self, level: str) -> str:
        return str(level).strip().lower()

    def _active_agent_name(self) -> str:
        return 'agent'

    def _runtime_autonomy_level(self) -> str:
        ac = getattr(self._controller, 'autonomy_controller', None)
        if ac is not None:
            return str(getattr(ac, 'autonomy_level', 'balanced'))
        return 'balanced'

    def _active_agent_config(self):
        return self._agent_config

    def _render_hud_bar(self) -> None:
        return None


def test_tui_apply_autonomy_level_updates_tool_schema_immediately(
    monkeypatch,
) -> None:
    """TUI HUD path must rebuild security_risk schema on the new autonomy level."""
    screen = _AutonomyScreenStub()
    agent_config = SimpleNamespace(mode='agent', autonomy_level='balanced')
    screen._agent_config = agent_config
    screen._config.get_agent_config = MagicMock(return_value=agent_config)

    planner = SimpleNamespace(
        _config=agent_config,
        build_toolset=MagicMock(
            side_effect=lambda: _toolset_for_autonomy(agent_config.autonomy_level)
        ),
    )
    agent = SimpleNamespace(
        config=agent_config,
        planner=planner,
        tools=_toolset_for_autonomy('balanced'),
    )
    screen._controller = SimpleNamespace(
        agent=agent,
        autonomy_controller=SimpleNamespace(autonomy_level='balanced'),
    )

    monkeypatch.setattr(
        'backend.cli.settings.query.get_persisted_autonomy_level',
        lambda _name=None: 'balanced',
    )
    monkeypatch.setattr(
        'backend.cli.settings.query.update_autonomy_level',
        lambda *_args, **_kwargs: None,
    )

    screen._apply_autonomy_level('full')

    assert agent_config.autonomy_level == 'full'
    assert screen._controller.autonomy_controller.autonomy_level == 'full'
    required = agent.tools[0]['function']['parameters'].get('required', [])
    assert 'security_risk' not in required
