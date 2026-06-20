"""Terminal session event handlers (run, input, read, observation).

Now appends one :class:`TerminalCard` per agent command instead of
upserting a single :class:`SessionPanel` per session.  A session
scrollback buffer tracks full output for detail screens.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from backend.cli.tui.helpers import (
    _join_secondary_parts,
    _sanitize_terminal_display_text,
)
from backend.cli.tui.renderer.helpers.terminal import (
    sanitize_terminal_observation_content,
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
    cwd = getattr(event, 'cwd', '') or ''
    label = orch._terminal_session_label(session_id) or session_id
    orch._create_terminal_scan_card(
        session_id=session_id,
        session_label=label,
        cwd=cwd,
        command=cmd,
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
    )


def _handle_terminal_read_action(
    orch: 'RendererEventProcessorMixin', event: TerminalReadAction
) -> None:
    # TerminalReadAction is a streaming trigger — keep the most recent
    # TerminalCard as the active one for output accumulation but don't
    # create a new card for every read pulse.
    pass


def _handle_terminal_observation(
    orch: 'RendererEventProcessorMixin', event: TerminalObservation
) -> None:
    content = event.content or ''
    session_id = getattr(event, 'session_id', '') or ''
    content = sanitize_terminal_observation_content(content)

    orch._accumulate_terminal_scrollback(session_id, content)
