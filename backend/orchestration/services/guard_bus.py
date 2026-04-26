"""GuardBus — single-emitter for guard system messages.

Rules enforced by the bus
-------------------------
1. **Budget**: at most one guard ``ErrorObservation`` per LLM turn.
   If the per-turn budget is already spent at an equal or higher priority, the
   signal is downgraded to a ``planning_directive`` only.  Phase 1's minimal
   ``_inject_turn_status`` surfaces that directive as ``<APP_DIRECTIVE>`` in the
   next LLM call.

2. **XOR emission**: a guard signal goes to history *or* sets
   ``planning_directive`` — never both.  The model sees a prior-turn observation
   in its message history; injecting the same text again as a directive in the
   next turn causes attention fragmentation and token waste.

3. **Priority** (lower integer = higher priority).  When multiple guards fire in
   the same turn the highest-priority signal wins the observation slot.

   ``HARD_STOP (1) > STUCK (2) > VERIFICATION (3) > CIRCUIT_WARNING (4) > CHECKPOINT (5)``

4. **Force flag**: terminal guard messages (circuit-tripped to STOPPED/PAUSED,
   unrecoverable errors) bypass the per-turn budget entirely — they must always
   reach the model because the session is about to end or permanently blocked.
"""

from __future__ import annotations

from typing import Any

from backend.core.logger import app_logger as logger
from backend.ledger import EventSource
from backend.ledger.observation import ErrorObservation
from backend.ledger.observation_cause import attach_observation_cause

# ── Priority constants ──────────────────────────────────────────────────────
#: Hard stop: circuit tripped to STOPPED/PAUSED, unrecoverable errors.
HARD_STOP: int = 1
#: Stuck-loop detection and replan directives.
STUCK: int = 2
#: Verification gate (stale-state churn detected).
VERIFICATION: int = 3
#: Circuit-breaker soft warnings and forced strategy switches.
CIRCUIT_WARNING: int = 4
#: Incomplete checkpoint handoff.
CHECKPOINT: int = 5

# ── Internal state key ──────────────────────────────────────────────────────
_STATE_KEY = '__guard_bus_slot__'


class _TurnSlot:
    """Tracks guard-observation state for one LLM turn."""

    __slots__ = ('turn', 'best_priority')

    def __init__(self, turn: int) -> None:
        self.turn = turn
        # Lowest priority-int seen so far (None = nothing emitted yet).
        self.best_priority: int | None = None

    def can_emit(self, priority: int) -> bool:
        """True if *priority* is allowed to emit an observation this turn."""
        return self.best_priority is None or priority < self.best_priority

    def record(self, priority: int) -> None:
        """Record that an observation was emitted at *priority*."""
        if self.best_priority is None or priority < self.best_priority:
            self.best_priority = priority


def _current_turn(state: Any) -> int:
    iflag = getattr(state, 'iteration_flag', None)
    if iflag is None:
        return 0
    try:
        return int(getattr(iflag, 'current_value', 0) or 0)
    except (TypeError, ValueError):
        return 0


def _get_slot(state: Any) -> _TurnSlot:
    """Get (or lazily create) the per-turn :class:`_TurnSlot` from *state.extra_data*."""
    extra = getattr(state, 'extra_data', None)
    turn = _current_turn(state)
    if not isinstance(extra, dict):
        # Shouldn't happen on a real State; return an orphan slot that won't persist.
        return _TurnSlot(turn)
    slot = extra.get(_STATE_KEY)
    if not isinstance(slot, _TurnSlot) or slot.turn != turn:
        slot = _TurnSlot(turn)
        extra[_STATE_KEY] = slot
    return slot


class GuardBus:
    """Thin helper used by guard services to emit observations + directives
    according to the per-turn budget and XOR rules.

    All methods are static so callers do not need an instance; the bus state
    lives on ``state.extra_data`` keyed by :data:`_STATE_KEY`.
    """

    @staticmethod
    def emit(
        controller: Any,
        priority: int,
        error_id: str,
        obs_content: str,
        directive: str | None = None,
        *,
        cause: Any = None,
        cause_context: str = '',
        force: bool = False,
    ) -> bool:
        """Emit a guard signal following the budget/XOR rules.

        Parameters
        ----------
        controller:
            The ``SessionOrchestrator`` (or compatible duck-type with
            ``.state``, ``.event_stream``).
        priority:
            One of :data:`HARD_STOP`, :data:`STUCK`, :data:`VERIFICATION`,
            :data:`CIRCUIT_WARNING`, :data:`CHECKPOINT`.
        error_id:
            ``error_id`` field for the :class:`~backend.ledger.observation.ErrorObservation`.
        obs_content:
            Observation text used when an observation is emitted.
        directive:
            Short action instruction for ``state.set_planning_directive()``.
            Used only when the observation budget is exhausted.
        cause:
            Optional originating action for :func:`attach_observation_cause`.
        cause_context:
            Context label passed to :func:`attach_observation_cause`.
        force:
            Bypass the per-turn budget (for terminal conditions that must
            always reach the model regardless of earlier signals).

        Returns
        -------
        bool
            ``True`` if an :class:`~backend.ledger.observation.ErrorObservation`
            was emitted; ``False`` if the signal was downgraded to
            directive-only (or suppressed).
        """
        state = getattr(controller, 'state', None)
        event_stream = getattr(controller, 'event_stream', None)
        if state is None or event_stream is None:
            logger.debug('GuardBus.emit: missing state/event_stream, skipping %s', error_id)
            return False

        slot = _get_slot(state)
        emit_obs = force or slot.can_emit(priority)

        if emit_obs:
            obs = ErrorObservation(content=obs_content, error_id=error_id)
            if cause is not None:
                attach_observation_cause(obs, cause, context=cause_context)
            event_stream.add_event(obs, EventSource.ENVIRONMENT)
            if not force:
                slot.record(priority)
            logger.debug(
                'GuardBus: emitted observation %s (priority=%d, turn=%d, force=%s)',
                error_id,
                priority,
                slot.turn,
                force,
            )
            # XOR rule: observation emitted → do NOT also set planning_directive.
            return True
        else:
            # Budget exhausted — downgrade to directive-only.
            if directive is not None and hasattr(state, 'set_planning_directive'):
                state.set_planning_directive(directive, source='GuardBus')
                logger.debug(
                    'GuardBus: budget spent; set directive for %s (priority=%d, turn=%d)',
                    error_id,
                    priority,
                    slot.turn,
                )
            return False
