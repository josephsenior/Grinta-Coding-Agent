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

_MICROCOMPACTABLE_TYPES: tuple[type[Observation], ...] = (
    CmdOutputObservation,
    FileReadObservation,
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


def apply_microcompact(
    events: list[Event],
    *,
    preserve_recent: int = DEFAULT_MICROCOMPACT_PRESERVE_RECENT,
) -> list[Event]:
    """Clear old tool observation bodies outside the preservation window."""
    if not events or preserve_recent < 1:
        return events
    cutoff = max(0, len(events) - preserve_recent)
    results: list[Event] = []
    cleared = 0
    for index, event in enumerate(events):
        if index < cutoff and _is_microcompactable(event):
            if isinstance(event, AgentCondensationObservation):
                results.append(event)
                continue
            results.append(_clear_observation_content(event))
            cleared += 1
            continue
        if index < cutoff and isinstance(event, Observation):
            if isinstance(event, (ErrorObservation, AgentCondensationObservation)):
                results.append(event)
                continue
        results.append(event)
    if cleared:
        from backend.core.logging.logger import app_logger as logger

        logger.debug('Microcompact cleared %d old tool observation bodies', cleared)
    return results


__all__ = ['apply_microcompact']
