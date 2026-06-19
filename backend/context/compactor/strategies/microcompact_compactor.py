"""Incremental tool-output shedder for medium-length sessions.

Replaces per-step observation masking for coding agents: old bulky tool
observations are cleared while recent tool loops stay intact.  Event count
is preserved so causal structure and compaction boundaries remain stable.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from backend.context.compactor.compactor import Compaction, Compactor
from backend.context.tool_result_storage import TOOL_RESULT_CLEARED_MESSAGE
from backend.context.view import View
from backend.ledger.observation import Observation
from backend.ledger.observation.agent import AgentCondensationObservation
from backend.ledger.observation.commands import CmdOutputObservation
from backend.ledger.observation.error import ErrorObservation
from backend.ledger.observation.files import FileReadObservation
from backend.ledger.serialization.event import event_from_dict, event_to_dict

if TYPE_CHECKING:
    from backend.inference.llm_registry import LLMRegistry
    from backend.ledger.event import Event

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


# Keywords that indicate important content worth preserving
_IMPORTANT_CONTENT_KEYWORDS: tuple[str, ...] = (
    'failed', 'error', 'traceback', 'exception',
    'passed', 'failed', 'assert', 'pytest',
    'exit code', 'exit_code', 'fatal',
    'warning', 'deprecated',
)

# Minimum content size below which clearing is not worth the risk
_MIN_CLEAR_SIZE = 200


def _should_preserve_observation(event: Event) -> bool:
    """Determine if an observation's content is important enough to preserve.

    Heuristics:
    1. Small observations (< 200 chars) are cheap to keep
    2. Observations with error/failure indicators are important
    3. Observations with test results are important
    """
    content = getattr(event, 'content', '') or ''
    if not isinstance(content, str):
        return False

    # Small observations are cheap to keep
    if len(content) < _MIN_CLEAR_SIZE:
        return True

    # Check for important content indicators
    lower = content.lower()
    for keyword in _IMPORTANT_CONTENT_KEYWORDS:
        if keyword in lower:
            return True

    return False


class MicrocompactCompactor(Compactor):
    """Clear old tool observation bodies outside a recent preservation window."""

    def __init__(self, preserve_recent: int = 80) -> None:
        if preserve_recent < 1:
            msg = f'preserve_recent ({preserve_recent}) must be positive'
            raise ValueError(msg)
        self.preserve_recent = preserve_recent
        super().__init__()

    async def compact(self, view: View) -> View | Compaction:
        results: list[Event] = []
        cutoff = max(0, len(view) - self.preserve_recent)
        cleared = 0
        for index, event in enumerate(view):
            if index < cutoff and _is_microcompactable(event):
                if isinstance(event, AgentCondensationObservation):
                    results.append(event)
                    continue
                # Preserve observations with important content
                if _should_preserve_observation(event):
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
            self.add_metadata('microcompact_cleared', cleared)
        return View(events=results)

    @classmethod
    def from_config(
        cls,
        config: Any,
        llm_registry: LLMRegistry,
    ) -> MicrocompactCompactor:
        from backend.core.pydantic_compat import model_dump_with_options

        return MicrocompactCompactor(
            **model_dump_with_options(config, exclude={'type'})
        )


def _register_config() -> None:
    from backend.core.config.compactor_config import MicrocompactCompactorConfig

    MicrocompactCompactor.register_config(MicrocompactCompactorConfig)


_register_config()

__all__ = ['MicrocompactCompactor']
