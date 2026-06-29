"""Compaction / condensation event handlers."""

from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING, Any

from backend.ledger.action.agent import CondensationAction
from backend.ledger.observation import AgentCondensationObservation

if TYPE_CHECKING:
    from backend.cli.tui.renderer.mixins.event_processor import (
        RendererEventProcessorMixin,
    )

# region agent log
_DEBUG_LOG_PATH = r'c:\Users\GIGABYTE\Desktop\Grinta\debug-f2dab3.log'


def _debug_log(hypothesis_id: str, location: str, message: str, data: dict) -> None:
    try:
        with open(_DEBUG_LOG_PATH, 'a', encoding='utf-8') as f:
            f.write(
                json.dumps(
                    {
                        'sessionId': 'f2dab3',
                        'hypothesisId': hypothesis_id,
                        'location': location,
                        'message': message,
                        'data': data,
                        'timestamp': int(time.time() * 1000),
                    }
                )
                + '\n'
            )
    except Exception:
        pass


# endregion


def _is_noop_condensation_action(action: CondensationAction) -> bool:
    if action.summary is not None:
        return False
    return len(action.pruned or []) == 0


def _condensation_summary_text(action: CondensationAction) -> str:
    summary = (action.summary or '').strip()
    if summary:
        return summary
    pruned = len(action.pruned or [])
    if pruned:
        return f'Context condensed ({pruned} events pruned).'
    return 'Context condensed.'


def _finish_compaction_card(orch: 'RendererEventProcessorMixin', *, summary: str) -> None:
    orch._compaction_transcript_active = False
    count = max(orch._condensation_count, 1)
    orch._condensation_count = count
    orch._hud.update_condensation_count(count)
    orch._complete_compaction_scan_card(summary=summary)


def show_compaction_started_card(orch: 'RendererEventProcessorMixin') -> None:
    """Ensure an in-progress compaction is visible in the transcript."""
    already_active = getattr(orch, '_compaction_transcript_active', False)
    # region agent log
    _debug_log(
        'E',
        'compaction.py:show_compaction_started_card',
        'start card requested',
        {
            'already_active': already_active,
            'has_pending_card': getattr(orch, '_pending_compaction_scan_card', None)
            is not None,
        },
    )
    # endregion
    if already_active:
        return
    count = max(orch._condensation_count + 1, 1)
    orch._condensation_count = count
    orch._compaction_transcript_active = True
    orch._create_compaction_scan_card()
    orch._hud.update_condensation_count(count)


def _handle_agent_condensation_observation(
    orch: 'RendererEventProcessorMixin', event: AgentCondensationObservation
) -> None:
    summary = (event.content or '').strip()
    # region agent log
    _debug_log(
        'A',
        'compaction.py:_handle_agent_condensation_observation',
        'condensation observation received',
        {
            'summary_len': len(summary),
            'summary_preview': summary[:120],
            'has_pending_card': getattr(orch, '_pending_compaction_scan_card', None)
            is not None,
        },
    )
    # endregion
    _finish_compaction_card(orch, summary=summary)


def _handle_condensation_action(
    orch: 'RendererEventProcessorMixin', event: CondensationAction
) -> None:
    """Complete the compaction card when condensation commits.

    Production runs emit ``CondensationAction`` to the event stream with the
    LLM/session summary attached. ``AgentCondensationObservation`` is synthesized
    only for prompt replay (``View.from_events``) and does not reach the TUI.
    """
    if _is_noop_condensation_action(event):
        orch._compaction_transcript_active = False
        return

    summary = _condensation_summary_text(event)
    # region agent log
    _debug_log(
        'B',
        'compaction.py:_handle_condensation_action',
        'condensation action received',
        {
            'summary_len': len(summary),
            'summary_preview': summary[:120],
            'pruned_count': len(event.pruned or []),
            'transcript_active': getattr(orch, '_compaction_transcript_active', False),
            'has_pending_card': getattr(orch, '_pending_compaction_scan_card', None)
            is not None,
        },
    )
    # endregion
    _finish_compaction_card(orch, summary=summary)


def _handle_compaction_trigger(orch: 'RendererEventProcessorMixin', event: Any) -> None:
    del event
    show_compaction_started_card(orch)
