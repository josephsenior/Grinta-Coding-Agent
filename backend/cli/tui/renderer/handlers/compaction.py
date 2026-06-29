"""Compaction / condensation event handlers."""

from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING, Any

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
    orch._compaction_transcript_active = False
    count = max(orch._condensation_count, 1)
    orch._condensation_count = count
    orch._hud.update_condensation_count(count)
    orch._complete_compaction_scan_card(summary=summary)


def _handle_compaction_trigger(orch: 'RendererEventProcessorMixin', event: Any) -> None:
    event_type = type(event).__name__
    summary = str(getattr(event, 'summary', '') or '').strip()
    pruned_count = len(getattr(event, 'pruned', []) or [])
    # region agent log
    _debug_log(
        'B',
        'compaction.py:_handle_compaction_trigger',
        'compaction trigger event',
        {
            'event_type': event_type,
            'summary_len': len(summary),
            'summary_preview': summary[:120],
            'pruned_count': pruned_count,
            'transcript_active': getattr(orch, '_compaction_transcript_active', False),
        },
    )
    # endregion
    show_compaction_started_card(orch)
