"""Task-aware compactor auto-selection.

Analyses the current task context (event patterns, session length, error
density, etc.) and selects the most appropriate compactor strategy.

When ``type = "auto"`` is set in ``[compactor]`` config, this module picks
the optimal compactor dynamically instead of using a fixed strategy.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Sequence

from backend.core.config.compactor_config import (
    AmortizedPruningCompactorConfig,
    CompactorConfig,
    NoOpCompactorConfig,
    ObservationMaskingCompactorConfig,
    RecentEventsCompactorConfig,
    SmartCompactorConfig,
    StructuredSummaryCompactorConfig,
)

if TYPE_CHECKING:
    from backend.ledger.event import Event

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Task signals extracted from the event stream
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class TaskSignals:
    """Lightweight summary of what is happening in the current session.

    Computed once per selection cycle from the event stream, then used by the
    selection heuristics.
    """

    total_events: int = 0
    error_count: int = 0
    user_message_count: int = 0
    code_edit_count: int = 0
    cmd_run_count: int = 0
    condensation_count: int = 0
    # Derived ratios
    error_ratio: float = 0.0
    avg_observation_length: float = 0.0


def _update_signals_from_event(sig: TaskSignals, ev: Event) -> tuple[int, int]:
    """Update counts for one event. Returns (total_obs_len_delta, obs_count_delta)."""
    from backend.ledger.action import CmdRunAction, MessageAction
    from backend.ledger.action.agent import CondensationAction
    from backend.ledger.event import EventSource
    from backend.ledger.observation import ErrorObservation, Observation

    obs_delta = 0
    len_delta = 0
    if isinstance(ev, ErrorObservation):
        sig.error_count += 1
    if isinstance(ev, MessageAction) and ev.source == EventSource.USER:
        sig.user_message_count += 1
    if isinstance(ev, CmdRunAction):
        sig.cmd_run_count += 1
    if isinstance(ev, CondensationAction):
        sig.condensation_count += 1
    if type(ev).__name__ == 'FileEditAction':
        sig.code_edit_count += 1
    if isinstance(ev, Observation):
        len_delta = len(ev.content)
        obs_delta = 1
    return (len_delta, obs_delta)


def compute_signals(events: Sequence[Event]) -> TaskSignals:
    """Compute :class:`TaskSignals` from a list of events.

    Import-safe: only uses ``isinstance`` against classes that are always
    available at this layer.
    """
    sig = TaskSignals(total_events=len(events))
    total_obs_len = 0
    obs_count = 0

    for ev in events:
        len_d, obs_d = _update_signals_from_event(sig, ev)
        total_obs_len += len_d
        obs_count += obs_d

    if sig.total_events > 0:
        sig.error_ratio = sig.error_count / sig.total_events
    if obs_count > 0:
        sig.avg_observation_length = total_obs_len / obs_count

    return sig


# ---------------------------------------------------------------------------
# Selection logic
# ---------------------------------------------------------------------------

# Thresholds (tunable via config in future)
_SHORT_SESSION = 30
_MEDIUM_SESSION = 150
_LONG_SESSION = 400
_HIGH_ERROR_RATIO = 0.15


def select_compactor_config(
    events: Sequence[Event],
    *,
    llm_config: object | None = None,
    fallback: CompactorConfig | None = None,
    supports_function_calling: bool = False,
) -> CompactorConfig:
    """Pick the best compactor config for the current task context.

    Parameters
    ----------
    events:
        The full (or recent) event stream to analyse.
    llm_config:
        LLM configuration reference to pass to LLM-based compactors.
        May be an LLMConfig instance (preferred) or a named LLM config section
        (e.g. ``"llm"``). When ``None`` LLM-based strategies are skipped.
    fallback:
        Config returned when events are too few to decide meaningfully.

    Returns:
    -------
    CompactorConfig
        The selected compactor configuration.
    """
    sig = compute_signals(events)

    logger.debug(
        'Compactor auto-select signals: events=%d errors=%d error_ratio=%.2f '
        'edits=%d cmds=%d condensations=%d',
        sig.total_events,
        sig.error_count,
        sig.error_ratio,
        sig.code_edit_count,
        sig.cmd_run_count,
        sig.condensation_count,
    )

    # 1. Very short session → no condensation needed
    if sig.total_events < _SHORT_SESSION:
        logger.info(
            'Auto-select compactor: noop (short session, %d events)', sig.total_events
        )
        return fallback or NoOpCompactorConfig()

    # 2. High error ratio → keep recent events for debugging context
    if sig.error_ratio >= _HIGH_ERROR_RATIO:
        logger.info(
            'Auto-select compactor: recent (high error ratio %.2f)', sig.error_ratio
        )
        return RecentEventsCompactorConfig(
            keep_first=3, max_events=min(sig.total_events, 80)
        )

    # 4. Long session with LLM available → structured summary (if function-calling) or smart
    if sig.total_events >= _LONG_SESSION:
        if llm_config:
            if supports_function_calling:
                logger.info(
                    'Auto-select compactor: structured (long session + function calling, %d events)',
                    sig.total_events,
                )
                return StructuredSummaryCompactorConfig(
                    llm_config=llm_config,
                    max_size=200,
                    keep_first=5,
                )
            logger.info(
                'Auto-select compactor: smart (long session, %d events)',
                sig.total_events,
            )
            return SmartCompactorConfig(
                llm_config=llm_config,
                max_size=200,
                keep_first=5,
            )
        # No LLM → amortized pruning
        logger.info(
            'Auto-select compactor: amortized (long session, no LLM, %d events)',
            sig.total_events,
        )
        return AmortizedPruningCompactorConfig(max_size=150, keep_first=3)

    # 5. Medium session → observation masking (light-weight)
    if sig.total_events >= _MEDIUM_SESSION:
        logger.info(
            'Auto-select compactor: observation_masking (medium session, %d events)',
            sig.total_events,
        )
        return ObservationMaskingCompactorConfig(attention_window=60)

    # 6. Default — noop / fallback
    logger.info('Auto-select compactor: fallback/noop (%d events)', sig.total_events)
    return fallback or NoOpCompactorConfig()
