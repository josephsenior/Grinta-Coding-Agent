"""Context window middleware for tool invocations."""

from __future__ import annotations

from typing import TYPE_CHECKING

from backend.core.logger import app_logger as logger
from backend.orchestration.tool_pipeline import ToolInvocationMiddleware

if TYPE_CHECKING:
    from backend.ledger.observation import Observation
    from backend.orchestration.session_orchestrator import SessionOrchestrator
    from backend.orchestration.tool_pipeline import ToolInvocationContext


class ContextWindowMiddleware(ToolInvocationMiddleware):
    """Emits proactive context-window utilization warnings at 70 % and 90 %.

    Mirrors the cost-threshold pattern used by ``BudgetGuardService`` but
    tracks token utilisation instead of dollar spend.  Fires at most once
    per threshold per session to avoid alert fatigue.

    Why this matters: without proactive warnings the LLM only learns the
    context window is full *after* the API returns an error — at which point
    App must trigger emergency condensation.  This middleware gives the LLM
    a chance to call ``request_condensation()`` voluntarily before overflow.
    """

    _THRESHOLDS: tuple[float, ...] = (0.70, 0.90)

    def __init__(self, controller: SessionOrchestrator) -> None:
        self.controller = controller
        self._alerted_thresholds: set[float] = set()

    async def observe(
        self, ctx: ToolInvocationContext, observation: Observation | None
    ) -> None:
        llm = getattr(self.controller.agent, 'llm', None)
        metrics = getattr(llm, 'metrics', None)
        if metrics is None:
            return
        token_usages = getattr(metrics, 'token_usages', [])
        if not token_usages:
            return
        last = token_usages[-1]
        context_window = getattr(last, 'context_window', 0)
        if context_window <= 0:
            return
        prompt_tokens = getattr(last, 'prompt_tokens', 0)
        pct = prompt_tokens / context_window
        for threshold in self._THRESHOLDS:
            if pct >= threshold and threshold not in self._alerted_thresholds:
                self._alerted_thresholds.add(threshold)
                self._emit_alert(threshold, prompt_tokens, context_window, pct)

    def _emit_alert(
        self,
        threshold: float,
        prompt_tokens: int,
        context_window: int,
        pct: float,
    ) -> None:
        pct_int = int(threshold * 100)
        content = (
            f'⚠️ Context window {pct_int}% full: '
            f'{prompt_tokens:,}/{context_window:,} tokens used. '
            'Call request_condensation() to free context space before overflow.'
        )
        logger.warning(
            'Context window threshold %d%% crossed for session %s — %d/%d tokens',
            pct_int,
            self.controller.id,
            prompt_tokens,
            context_window,
            extra={'session_id': self.controller.id},
        )
        try:
            from backend.ledger.event import EventSource
            from backend.ledger.observation.status import StatusObservation

            obs = StatusObservation(
                content=content,
                status_type='context_window_alert',
                extras={
                    'threshold': threshold,
                    'pct_used': round(pct, 4),
                    'prompt_tokens': prompt_tokens,
                    'context_window': context_window,
                },
            )
            self.controller.event_stream.add_event(obs, EventSource.ENVIRONMENT)
        except Exception:
            logger.debug(
                'Failed to emit context window alert for session %s',
                self.controller.id,
                exc_info=True,
            )
