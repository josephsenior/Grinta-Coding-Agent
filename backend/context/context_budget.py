"""Token budget estimation for the unified context pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from backend.context.prompt_window import estimate_events_tokens
from backend.core.constants import DEFAULT_COMPACTION_RESERVED_SUMMARY_TOKENS
from backend.inference.provider_capabilities import model_token_correction

if TYPE_CHECKING:
    from backend.ledger.event import Event
    from backend.orchestration.state.state import State


@dataclass(frozen=True)
class ContextBudget:
    """Estimates prompt pressure and autocompact threshold for post-boundary events."""

    estimated_tokens: int
    effective_window: int
    autocompact_threshold: int
    reserved_summary_tokens: int = DEFAULT_COMPACTION_RESERVED_SUMMARY_TOKENS

    @property
    def should_autocompact(self) -> bool:
        return self.estimated_tokens >= self.autocompact_threshold

    @classmethod
    def from_events(
        cls,
        events: list[Event],
        *,
        llm_config: object | None = None,
        state: State | None = None,
    ) -> ContextBudget:
        """Build a budget from post-boundary events and optional API usage."""
        effective_window = _effective_context_window(llm_config)
        reserved = DEFAULT_COMPACTION_RESERVED_SUMMARY_TOKENS
        threshold = max(
            1,
            effective_window - reserved
            if effective_window > reserved
            else effective_window,
        )
        estimated = _estimate_tokens(events, llm_config=llm_config, state=state)
        return cls(
            estimated_tokens=estimated,
            effective_window=effective_window,
            autocompact_threshold=threshold,
            reserved_summary_tokens=reserved,
        )


def _effective_context_window(llm_config: object | None) -> int:
    if llm_config is None:
        return 200_000
    for attr in ('max_input_tokens', 'context_window', 'max_context_tokens'):
        value = getattr(llm_config, attr, None)
        if isinstance(value, int) and value > 0:
            return value
    budget = getattr(llm_config, 'prompt_history_token_budget', None)
    if isinstance(budget, int) and budget > 0:
        ratio = getattr(llm_config, 'prompt_history_budget_ratio', 0.5)
        if isinstance(ratio, (int, float)) and ratio > 0:
            return int(budget / ratio)
        return budget * 2
    return 200_000


def _estimate_tokens(
    events: list[Event],
    *,
    llm_config: object | None,
    state: State | None,
) -> int:
    api_tokens = _last_api_prompt_tokens(state)
    if api_tokens > 0:
        tail = estimate_events_tokens(events[-12:])
        return api_tokens + tail
    raw = estimate_events_tokens(events)
    model = str(getattr(llm_config, 'model', '') or '')
    factor, _ = model_token_correction(model)
    return int(raw * factor)


def _last_api_prompt_tokens(state: State | None) -> int:
    if state is None:
        return 0
    metrics = getattr(state, 'metrics', None)
    usages = getattr(metrics, 'token_usages', None) if metrics is not None else None
    if not usages:
        return 0
    last = usages[-1]
    prompt_tokens = getattr(last, 'prompt_tokens', 0)
    if isinstance(prompt_tokens, int) and prompt_tokens > 0:
        return prompt_tokens
    total = getattr(last, 'total_tokens', 0)
    return total if isinstance(total, int) and total > 0 else 0


__all__ = ['ContextBudget']
