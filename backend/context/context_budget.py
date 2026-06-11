"""Token budget estimation for the unified context pipeline."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from backend.context.prompt_window import estimate_events_tokens
from backend.core.constants import (
    DEFAULT_BOUNDARY_COMPACT_COOLDOWN_SECONDS,
    DEFAULT_COMPACTION_RESERVED_SUMMARY_TOKENS,
)
from backend.inference.context_limits import limits_from_config
from backend.inference.provider_capabilities import model_token_correction

if TYPE_CHECKING:
    from backend.ledger.event import Event
    from backend.orchestration.state.state import State

_POST_COMPACT_BASELINE_KEY = 'post_compact_baseline_tokens'
_LAST_BOUNDARY_COMPACT_KEY = 'last_boundary_compact_at'


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


def record_post_compact_baseline(state: object, events: list[Event]) -> None:
    """Store post-boundary token baseline after a committed compaction."""
    if not hasattr(state, 'set_extra'):
        return
    pipe = dict(getattr(state, 'extra_data', {}).get('context_pipeline_state', {}))
    pipe[_POST_COMPACT_BASELINE_KEY] = estimate_events_tokens(events)
    pipe[_LAST_BOUNDARY_COMPACT_KEY] = time.time()
    state.set_extra('context_pipeline_state', pipe, source='ContextBudget')  # type: ignore[attr-defined]


def _effective_context_window(llm_config: object | None) -> int:
    limits = limits_from_config(llm_config, unknown_default=True)
    if limits.usable_input_tokens is not None:
        return limits.usable_input_tokens
    return 200_000


def _pipeline_state(state: State | None) -> dict[str, Any]:
    if state is None:
        return {}
    raw = getattr(state, 'extra_data', {}).get('context_pipeline_state')
    return dict(raw) if isinstance(raw, dict) else {}


def _recent_compaction(state: State | None) -> bool:
    pipe = _pipeline_state(state)
    last = pipe.get(_LAST_BOUNDARY_COMPACT_KEY)
    if not isinstance(last, (int, float)):
        return False
    return (time.time() - last) < DEFAULT_BOUNDARY_COMPACT_COOLDOWN_SECONDS


def _estimate_tokens(
    events: list[Event],
    *,
    llm_config: object | None,
    state: State | None,
) -> int:
    if _recent_compaction(state):
        raw = estimate_events_tokens(events)
        model = str(getattr(llm_config, 'model', '') or '')
        factor, _ = model_token_correction(model)
        return int(raw * factor)

    pipe = _pipeline_state(state)
    baseline = pipe.get(_POST_COMPACT_BASELINE_KEY)
    if isinstance(baseline, int) and baseline > 0 and len(events) <= 120:
        tail = estimate_events_tokens(events[-12:])
        return baseline + tail

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


__all__ = ['ContextBudget', 'record_post_compact_baseline']
