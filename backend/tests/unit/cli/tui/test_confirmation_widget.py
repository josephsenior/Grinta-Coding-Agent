from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock, PropertyMock

import pytest
from rich.console import Console as RichConsole
from textual.containers import Horizontal
from textual.widgets import Button, Static

from backend.cli.tui.app import ConfirmWidget, GrintaScreen
from backend.cli.tui.main import GrintaTUIApp
from backend.core.enums import ActionSecurityRisk


@pytest.fixture
def mock_config():
    config = MagicMock()
    type(config).project_root = PropertyMock(return_value=None)

    llm_config = MagicMock()
    llm_config.model = 'openai/gpt-4o'
    llm_config.base_url = None
    config.get_llm_config.return_value = llm_config
    config.get_llm_config_from_agent.return_value = llm_config
    return config


def _get_screen(app: GrintaTUIApp) -> GrintaScreen:
    return app.screen  # type: ignore[return-value]


def test_tui_confirmation_normalizes_enum_risk() -> None:
    assert GrintaScreen._normalize_risk_key(ActionSecurityRisk.HIGH) == 'HIGH'
    assert GrintaScreen._normalize_risk_key(ActionSecurityRisk.MEDIUM) == 'MEDIUM'
    assert GrintaScreen._normalize_risk_key(ActionSecurityRisk.LOW) == 'LOW'
    assert GrintaScreen._normalize_risk_key(ActionSecurityRisk.UNKNOWN) == 'UNKNOWN'
    assert GrintaScreen._normalize_risk_key('2') == 'HIGH'


@pytest.mark.asyncio
async def test_tui_confirmation_widget_renders_visible_content(
    mock_config,
    monkeypatch,
) -> None:
    monkeypatch.setattr(GrintaScreen, '_start_background_bootstrap', lambda self: None)
    console = RichConsole()
    loop = asyncio.get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()

        screen = _get_screen(app)
        widget = screen.query_one('#confirm-widget', ConfirmWidget)
        widget.configure(
            'Run Command',
            'High',
            'bold red',
            'rm -rf /',
            [('approve', 'Accept'), ('reject', 'Reject')],
            recommended=0,
        )
        widget.show()
        await pilot.pause()

        bar = widget.query_one('#confirm-bar', Horizontal)
        info = widget.query_one('#confirm-info', Static)
        buttons = list(widget.query('Button').results())

        assert widget.display is True
        assert bar.region.height > 0
        assert info.region.height > 0
        assert len(buttons) == 2
        assert all(button.region.height > 0 for button in buttons)
        assert 'Agent wants to execute' in str(info.renderable)


@pytest.mark.parametrize(
    ('button_key', 'expected_decision'),
    [
        ('approve', 'approve'),
        ('always', 'always'),
    ],
)
@pytest.mark.asyncio
async def test_tui_confirmation_widget_acceptance_decision_survives_hide(
    mock_config,
    monkeypatch,
    button_key: str,
    expected_decision: str,
) -> None:
    monkeypatch.setattr(GrintaScreen, '_start_background_bootstrap', lambda self: None)
    console = RichConsole()
    loop = asyncio.get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()

        screen = _get_screen(app)
        widget = screen.query_one('#confirm-widget', ConfirmWidget)
        widget.configure(
            'Run Command',
            'High',
            'bold red',
            'rm -rf /',
            [('approve', 'Accept'), ('always', 'Always'), ('reject', 'Reject')],
            recommended=0,
        )
        widget.show()
        await pilot.pause()

        waiter = asyncio.create_task(widget.wait_for_decision())
        button = widget.query_one(f'#confirm-{button_key}', Button)
        widget.on_button_pressed(SimpleNamespace(button=button))  # type: ignore[arg-type]

        result = await asyncio.wait_for(waiter, timeout=1)
        assert result == expected_decision
        assert widget.display is False
