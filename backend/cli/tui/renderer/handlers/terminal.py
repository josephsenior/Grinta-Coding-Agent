"""Terminal session handlers with inline commands and bounded output tails.

Appends one :class:`TerminalCard` per agent command. A session scrollback
buffer retains complete output for the overflow detail view.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from backend.cli.tui.helpers import (
    _join_secondary_parts,
    _sanitize_terminal_display_text,
)
from backend.cli.tui.renderer.helpers.terminal import (
    sanitize_terminal_observation_content,
)
from backend.ledger.action import (
    TerminalCloseAction,
    TerminalInputAction,
    TerminalListAction,
    TerminalReadAction,
    TerminalRunAction,
    TerminalWaitAction,
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
    cwd = getattr(event, 'cwd', '') or ''
    label = orch._terminal_session_label(session_id) or session_id
    orch._create_terminal_scan_card(
        session_id=session_id,
        session_label=label,
        cwd=cwd,
        command=cmd,
        action_id=getattr(event, 'id', None),
        action_kind='terminal_run',
    )


def _handle_terminal_input_action(
    orch: 'RendererEventProcessorMixin', event: TerminalInputAction
) -> None:
    session_id = getattr(event, 'session_id', '') or ''
    submitted = _sanitize_terminal_display_text(getattr(event, 'input', '') or '')
    label = orch._terminal_session_label(session_id) or session_id
    orch._create_terminal_scan_card(
        session_id=session_id,
        session_label=label,
        cwd='',
        command=submitted,
        action_id=getattr(event, 'id', None),
        action_kind='terminal_input',
    )


def _handle_terminal_read_action(
    orch: 'RendererEventProcessorMixin', event: TerminalReadAction
) -> None:
    # TerminalReadAction is a streaming trigger — keep the most recent
    # TerminalCard as the active one for output accumulation but don't
    # create a new card for every read pulse.
    pass


def _handle_terminal_wait_action(
    orch: 'RendererEventProcessorMixin', event: TerminalWaitAction
) -> None:
    # Wait polls for output patterns — silent in the transcript (like read).
    del orch, event


def _handle_terminal_list_action(
    orch: 'RendererEventProcessorMixin', event: TerminalListAction
) -> None:
    # Session listing is bookkeeping — no transcript card.
    del orch, event


def _handle_terminal_close_action(
    orch: 'RendererEventProcessorMixin', event: TerminalCloseAction
) -> None:
    orch._begin_terminal_close_card(
        getattr(event, 'id', -1), getattr(event, 'session_id', '') or ''
    )


def _take_terminal_observation_card(
    orch: 'RendererEventProcessorMixin', action_id: int | None
) -> tuple[Any, str] | None:
    kind = orch._tool_card_kind(action_id)
    if kind is None:
        return None
    card = orch._take_tool_card(action_id, expected_kind=kind)
    if card is None:
        return None
    return card, kind


def _remember_terminal_observation_card(
    orch: 'RendererEventProcessorMixin', session_id: str, card: Any
) -> None:
    if not session_id:
        return
    orch._pending_terminal_scan_cards[session_id] = card
    if hasattr(orch, '_terminal_cards_by_session'):
        orch._terminal_cards_by_session[session_id] = card


def _terminal_observation_state(kind: str, ok: bool) -> str:
    if kind == 'terminal_run' and ok:
        return 'background'
    return 'done' if ok else 'failed'


def _handle_terminal_observation(
    orch: 'RendererEventProcessorMixin', event: TerminalObservation
) -> None:
    content = event.content or ''
    session_id = getattr(event, 'session_id', '') or ''
    content = sanitize_terminal_observation_content(content)

    orch._accumulate_terminal_scrollback(session_id, content)
    resolved = _take_terminal_observation_card(orch, getattr(event, 'cause', None))
    if resolved is None:
        return
    card, kind = resolved

    tool_result = getattr(event, 'tool_result', None)
    ok = tool_result.get('ok', True) if isinstance(tool_result, dict) else True
    _remember_terminal_observation_card(orch, session_id, card)

    orch._complete_terminal_scan_card(
        card,
        session_id=session_id,
        session_label=orch._terminal_session_label(session_id) or session_id,
        scrollback='\n'.join(orch._terminal_scrollback_by_session.get(session_id, [])),
        state=_terminal_observation_state(kind, ok),
    )
