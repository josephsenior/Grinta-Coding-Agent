"""Age-based tool-output shedding for the unified context pipeline (Layer 3)."""

from __future__ import annotations

from backend.context.tool_result_storage import TOOL_RESULT_CLEARED_MESSAGE
from backend.core.constants import DEFAULT_MICROCOMPACT_PRESERVE_RECENT
from backend.ledger.event import Event
from backend.ledger.observation import Observation
from backend.ledger.observation.agent import AgentCondensationObservation
from backend.ledger.observation.commands import CmdOutputObservation
from backend.ledger.observation.error import ErrorObservation
from backend.ledger.observation.files import FileReadObservation
from backend.ledger.serialization.event import event_from_dict, event_to_dict

MICROCOMPACT_CLEARED_IDS_KEY = 'microcompact_cleared_event_ids'

_MICROCOMPACTABLE_TYPES: tuple[type[Observation], ...] = (
    CmdOutputObservation,
    FileReadObservation,
)


def get_microcompact_cleared_ids(state: object | None) -> set[int]:
    """Return event ids whose tool bodies were frozen cleared by microcompact."""
    if state is None:
        return set()
    extra = getattr(state, 'extra_data', None)
    if not isinstance(extra, dict):
        return set()
    raw = extra.get(MICROCOMPACT_CLEARED_IDS_KEY)
    if not isinstance(raw, (list, tuple, set)):
        return set()
    cleared: set[int] = set()
    for item in raw:
        if isinstance(item, int) and item > 0:
            cleared.add(item)
    return cleared


def clear_microcompact_cleared_ids(state: object | None) -> None:
    """Drop all frozen microcompact decisions (e.g. after compaction boundary)."""
    if state is None or not hasattr(state, 'set_extra'):
        return
    extra = getattr(state, 'extra_data', None)
    if not isinstance(extra, dict) or MICROCOMPACT_CLEARED_IDS_KEY not in extra:
        return
    state.set_extra(  # type: ignore[attr-defined]
        MICROCOMPACT_CLEARED_IDS_KEY,
        [],
        source='microcompact',
    )


def _persist_cleared_id(state: object, event_id: int) -> None:
    if not hasattr(state, 'set_extra'):
        return
    cleared = get_microcompact_cleared_ids(state)
    if event_id in cleared:
        return
    cleared.add(event_id)
    state.set_extra(  # type: ignore[attr-defined]
        MICROCOMPACT_CLEARED_IDS_KEY,
        sorted(cleared),
        source='microcompact',
    )


def _is_microcompactable(event: Event) -> bool:
    if isinstance(event, _MICROCOMPACTABLE_TYPES):
        return True
    if not isinstance(event, Observation):
        return False
    name = type(event).__name__
    return name in {
        'MCPObservation',
        'TerminalObservation',
        'LspQueryObservation',
        'GrepObservation',
        'GlobObservation',
        'BrowserScreenshotObservation',
        'DebuggerObservation',
    }


def _clear_observation_content(event: Event) -> Event:
    copied = event_from_dict(event_to_dict(event))
    try:
        setattr(copied, 'content', TOOL_RESULT_CLEARED_MESSAGE)
    except Exception:
        pass
    return copied


def _should_clear_outside_window(event: Event, *, index: int, cutoff: int) -> bool:
    if index >= cutoff:
        return False
    if isinstance(event, AgentCondensationObservation):
        return False
    if _is_microcompactable(event):
        return True
    if isinstance(event, Observation):
        return not isinstance(event, ErrorObservation)
    return False


def apply_microcompact(
    events: list[Event],
    *,
    preserve_recent: int = DEFAULT_MICROCOMPACT_PRESERVE_RECENT,
    state: object | None = None,
) -> list[Event]:
    """Clear old tool observation bodies outside the preservation window.

    Cleared event ids are recorded in *state* so later prompt projections
    reuse the same cleared bodies instead of re-deriving the sliding window.
    """
    if not events or preserve_recent < 1:
        return events

    frozen_cleared = get_microcompact_cleared_ids(state)
    cutoff = max(0, len(events) - preserve_recent)
    results: list[Event] = []
    newly_cleared = 0

    for index, event in enumerate(events):
        event_id = getattr(event, 'id', None)

        if isinstance(event_id, int) and event_id in frozen_cleared:
            if _is_microcompactable(event):
                results.append(_clear_observation_content(event))
            else:
                results.append(event)
            continue

        if _should_clear_outside_window(event, index=index, cutoff=cutoff):
            cleared = _clear_observation_content(event)
            if state is not None and isinstance(event_id, int):
                _persist_cleared_id(state, event_id)
                frozen_cleared.add(event_id)
            results.append(cleared)
            newly_cleared += 1
            continue

        results.append(event)

    if newly_cleared:
        from backend.core.logging.logger import app_logger as logger

        logger.debug(
            'Microcompact cleared %d old tool observation bodies (frozen_total=%d)',
            newly_cleared,
            len(frozen_cleared),
        )
    return results


__all__ = [
    'MICROCOMPACT_CLEARED_IDS_KEY',
    'apply_microcompact',
    'clear_microcompact_cleared_ids',
    'get_microcompact_cleared_ids',
]
