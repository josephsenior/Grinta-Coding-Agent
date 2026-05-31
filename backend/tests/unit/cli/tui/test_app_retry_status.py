from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest

from backend.cli.hud import HUDBar
from backend.cli.reasoning_display import ReasoningDisplay
from backend.cli.tui.app import GrintaScreen, TUIRenderer
from backend.core.schemas import AgentState
from backend.ledger.observation import AgentStateChangedObservation, StatusObservation


def test_grinta_screen_resolves_backoff_display_state() -> None:
    display, color = GrintaScreen._resolve_state_display('Backoff 1/3 (retrying in 5s)')

    assert display == 'Backoff 1/3 (retrying in 5s)'
    assert color == GrintaScreen._STATE_COLORS['backoff']


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
    assert any('provider' in str(a).lower() for a in args) or any('provider' in str(v).lower() for v in kwargs.values())


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
