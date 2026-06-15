"""Terminal session event handlers (run, input, read, observation)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from backend.cli.tui.helpers import (
    _join_secondary_parts,
    _sanitize_terminal_display_text,
)
from backend.cli.tui.renderer.helpers.terminal import (
    sanitize_terminal_observation_content,
    terminal_secondary_kind,
)
from backend.ledger.action import (
    TerminalInputAction,
    TerminalReadAction,
    TerminalRunAction,
)
from backend.ledger.observation import TerminalObservation

if TYPE_CHECKING:
    from backend.cli.tui.renderer.mixins.event_processor import (
        RendererEventProcessorMixin,
    )


def _terminal_secondary_text(
    orch: 'RendererEventProcessorMixin',
    session_id: str,
    exit_code: int | None,
    state: str | None,
) -> str:
    label = orch._terminal_session_label(session_id)
    status = f'exit {exit_code}' if exit_code is not None else (state or None)
    return _join_secondary_parts(label, status)


def _handle_terminal_run_action(
    orch: 'RendererEventProcessorMixin', event: TerminalRunAction
) -> None:
    cmd = getattr(event, 'command', '') or ''
    session_id = getattr(event, 'session_id', '') or ''
    detail = orch._terminal_card_detail(session_id, cmd)
    orch._upsert_terminal_session_card(
        session_id=session_id,
        verb='Started',
        detail=detail,
        secondary=_join_secondary_parts(
            orch._terminal_session_label(session_id),
            'starting session',
        ),
        secondary_kind='neutral',
        processing=True,
    )


def _handle_terminal_input_action(
    orch: 'RendererEventProcessorMixin', event: TerminalInputAction
) -> None:
    session_id = getattr(event, 'session_id', '') or ''
    submitted = _sanitize_terminal_display_text(getattr(event, 'input', '') or '')
    detail = orch._terminal_card_detail(session_id, submitted)
    orch._upsert_terminal_session_card(
        session_id=session_id,
        verb='Sent',
        detail=detail,
        secondary=_join_secondary_parts(
            orch._terminal_session_label(session_id),
            'awaiting output',
        ),
        secondary_kind='neutral',
        extra_content=f'$ {submitted.rstrip()}' if submitted.strip() else None,
        processing=True,
    )


def _handle_terminal_read_action(
    orch: 'RendererEventProcessorMixin', event: TerminalReadAction
) -> None:
    session_id = getattr(event, 'session_id', '') or ''
    orch._upsert_terminal_session_card(
        session_id=session_id,
        verb='Reading',
        detail=orch._terminal_card_detail(session_id),
        secondary=_join_secondary_parts(
            orch._terminal_session_label(session_id),
            'streaming output',
        ),
        secondary_kind='neutral',
        processing=True,
    )


def _handle_terminal_observation(
    orch: 'RendererEventProcessorMixin', event: TerminalObservation
) -> None:
    content = event.content or ''
    session_id = getattr(event, 'session_id', '') or ''
    exit_code = getattr(event, 'exit_code', None)
    state = getattr(event, 'state', None)
    secondary = _terminal_secondary_text(orch, session_id, exit_code, state)
    secondary_kind = terminal_secondary_kind(exit_code)
    content = sanitize_terminal_observation_content(content)
    orch._upsert_terminal_session_card(
        session_id=session_id,
        verb='Output',
        detail=orch._terminal_card_detail(session_id),
        secondary=secondary,
        secondary_kind=secondary_kind,
        extra_content=content or None,
        processing=exit_code is None,
        collapse_after_update=exit_code == 0 and bool(content),
    )
