from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest

from backend.cli.display.hud import HUDBar
from backend.cli.display.reasoning_display import ReasoningDisplay
from backend.cli.tui.app import GrintaScreen, TUIRenderer
from backend.core.enums import AgentState
from backend.ledger.observation import AgentStateChangedObservation, StatusObservation


def test_grinta_screen_resolves_backoff_display_state() -> None:
    display, color = GrintaScreen._resolve_state_display('Backoff 1/3 (retrying in 5s)')

    assert display == 'Backoff 1/3 (retrying in 5s)'
    assert color == GrintaScreen._STATE_COLORS['backoff']


def test_grinta_screen_finished_state_displays_ready() -> None:
    display, color = GrintaScreen._resolve_state_display('finished')

    assert display == 'Ready'
    assert color == GrintaScreen._STATE_COLORS['finished']


@pytest.mark.parametrize(
    ('raw_state', 'expected'),
    [
        ('running', True),
        ('starting', True),
        ('loading', True),
        ('awaiting_user_confirmation', True),
        ('Backoff 1/3 (retrying in 5s)', True),
        ('Rate Limited', True),
        ('Ready', False),
        ('finished', False),
    ],
)
def test_grinta_screen_hud_pulse_states(raw_state: str, expected: bool) -> None:
    assert GrintaScreen._hud_state_should_pulse(raw_state) is expected


def test_grinta_screen_hud_pulse_line_uses_animated_bullet() -> None:
    line = GrintaScreen._build_hud_line1(
        GrintaScreen,
        'Starting',
        GrintaScreen._STATE_COLORS['starting'],
        raw_state='starting',
    )

    assert '◉' in line or '●' in line
    assert 'Starting' in line
    assert '[#f6ff8f]' in line or '[#b8bb62]' in line


def test_grinta_screen_append_turn_duration_for_finished() -> None:
    screen = GrintaScreen.__new__(GrintaScreen)
    screen._last_turn_duration = '2m 3s'

    result = screen._append_turn_duration('Ready', 'finished')

    assert result == 'Ready [worked for 2m 3s]'


@pytest.mark.asyncio
async def test_tui_renderer_surfaces_retry_pending_status() -> None:
    hud = HUDBar()
    tui = MagicMock()
    renderer = TUIRenderer(
        console=MagicMock(),
        hud=hud,
        reasoning=ReasoningDisplay(),
        tui=tui,
        loop=asyncio.get_running_loop(),
    )

    renderer._process_event(
        StatusObservation(
            content='',
            status_type='retry_pending',
            extras={
                'attempt': 1,
                'max_attempts': 3,
                'delay_seconds': 5.0,
                'reason': 'APIConnectionError',
            },
        )
    )

    assert hud.state.ledger_status == 'Backoff'
    assert hud.state.agent_state_label == 'Backoff 1/3 (retrying in 5s)'
    tui.set_agent_phase.assert_called_once_with('Backoff 1/3 (retrying in 5s)')
    tui.set_retry_status.assert_called_once()


@pytest.mark.asyncio
async def test_tui_renderer_surfaces_llm_stream_retry_pending_status() -> None:
    hud = HUDBar()
    tui = MagicMock()
    renderer = TUIRenderer(
        console=MagicMock(),
        hud=hud,
        reasoning=ReasoningDisplay(),
        tui=tui,
        loop=asyncio.get_running_loop(),
    )

    renderer._process_event(
        StatusObservation(
            content='',
            status_type='llm_retry_pending',
            extras={
                'attempt': 1,
                'max_attempts': 3,
                'delay_seconds': 2.0,
                'reason': 'APIConnectionError',
                'source': 'llm_stream',
            },
        )
    )

    assert hud.state.agent_state_label == 'Backoff 1/3 (retrying in 2s)'
    tui.set_retry_status.assert_called_once()
    call_args = tui.set_retry_status.call_args
    assert call_args is not None
    args, kwargs = call_args
    assert any('provider' in str(a).lower() for a in args) or any(
        'provider' in str(v).lower() for v in kwargs.values()
    )


@pytest.mark.asyncio
async def test_tui_renderer_preserves_retry_label_on_rate_limited_state() -> None:
    hud = HUDBar()
    tui = MagicMock()
    renderer = TUIRenderer(
        console=MagicMock(),
        hud=hud,
        reasoning=ReasoningDisplay(),
        tui=tui,
        loop=asyncio.get_running_loop(),
    )

    renderer._process_event(
        StatusObservation(
            content='',
            status_type='retry_pending',
            extras={
                'attempt': 2,
                'max_attempts': 3,
                'delay_seconds': 8.0,
                'reason': 'Timeout',
            },
        )
    )
    renderer._handle_state_change(
        AgentStateChangedObservation('', AgentState.RATE_LIMITED)
    )

    assert hud.state.ledger_status == 'Backoff'
    assert hud.state.agent_state_label == 'Backoff 2/3 (retrying in 8s)'
