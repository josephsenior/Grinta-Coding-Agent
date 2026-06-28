"""Token budget estimation for the unified context pipeline."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from backend.context.prompt.prompt_window import estimate_prompt_events_tokens
from backend.core.constants import (
    DEFAULT_BOUNDARY_COMPACT_COOLDOWN_SECONDS,
    DEFAULT_COMPACTION_RESERVED_SUMMARY_TOKENS,
)
from backend.inference.capabilities.context_limits import limits_from_config
from backend.inference.capabilities.provider_capabilities import model_token_correction

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
    fixed_prompt_reserve_tokens: int = 0

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
        from backend.context.prompt.prompt_window import (
            reset_current_tokenizer_model,
            set_current_tokenizer_model,
        )

        effective_window = _effective_context_window(llm_config)
        reserved = DEFAULT_COMPACTION_RESERVED_SUMMARY_TOKENS
        fixed_prompt_reserve = _fixed_prompt_reserve_tokens(state)
        threshold = max(
            1,
            effective_window - reserved - fixed_prompt_reserve
            if effective_window > reserved + fixed_prompt_reserve
            else effective_window,
        )
        model_id = str(getattr(llm_config, 'model', '') or '') if llm_config else ''
        model_token = set_current_tokenizer_model(model_id or None)
        try:
            estimated = _estimate_tokens(
                events, llm_config=llm_config, state=state
            )
        finally:
            reset_current_tokenizer_model(model_token)
        return cls(
            estimated_tokens=estimated,
            effective_window=effective_window,
            autocompact_threshold=threshold,
            reserved_summary_tokens=reserved,
            fixed_prompt_reserve_tokens=fixed_prompt_reserve,
        )


def record_post_compact_baseline(state: object, events: list[Event]) -> None:
    """Store post-boundary token baseline after a committed compaction."""
    if not hasattr(state, 'set_extra'):
        return
    pipe = dict(getattr(state, 'extra_data', {}).get('context_pipeline_state', {}))
    pipe[_POST_COMPACT_BASELINE_KEY] = estimate_prompt_events_tokens(events)
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
        raw = estimate_prompt_events_tokens(events)
        model = str(getattr(llm_config, 'model', '') or '')
        factor, _ = model_token_correction(model)
        return int(raw * factor)

    pipe = _pipeline_state(state)
    baseline = pipe.get(_POST_COMPACT_BASELINE_KEY)
    if isinstance(baseline, int) and baseline > 0 and len(events) <= 120:
        # ``baseline`` was captured immediately after a compaction
        # boundary, so it reflects the post-compaction history. After
        # that, we add the *tail* of new events. **Critically**, the
        # baseline can be stale if a single large tool result or user
        # payload slipped in mid-history. We therefore add any event
        # whose projected token count is above a "large event" floor
        # on top of the baseline + tail.
        large_extra = _sum_large_event_tokens(events[:-12] if len(events) > 12 else [])
        tail = estimate_prompt_events_tokens(events[-12:])
        return baseline + tail + large_extra

    api_tokens = _last_dynamic_prompt_tokens(state)
    if api_tokens > 0:
        large_extra = _sum_large_event_tokens(events[:-12] if len(events) > 12 else [])
        tail = estimate_prompt_events_tokens(events[-12:])
        return api_tokens + tail + large_extra
    raw = estimate_prompt_events_tokens(events)
    model = str(getattr(llm_config, 'model', '') or '')
    factor, _ = model_token_correction(model)
    return int(raw * factor)


_LARGE_EVENT_TOKEN_FLOOR = 1_000
"""Any single event whose estimated token count is above this floor is
counted individually instead of being folded into a ``baseline`` cache.
This prevents the autocompact gate from underestimating when one large
tool result (e.g. an 80k-token pytest log) sits in the middle of the
history.
"""


def _sum_large_event_tokens(events: list[Event]) -> int:
    """Return the sum of token estimates for events over the large floor."""
    if not events:
        return 0
    total = 0
    for event in events:
        # Use a cheap per-event estimate to avoid double-counting tiny
        # observations that the prompt-window already covered.
        est = estimate_prompt_events_tokens([event])
        if est >= _LARGE_EVENT_TOKEN_FLOOR:
            total += est
    return total


def _fixed_prompt_reserve_tokens(state: State | None) -> int:
    """Return static/tool/context packet tokens from the last measured request."""
    if state is None:
        return 0
    extra = getattr(state, 'extra_data', None)
    if not isinstance(extra, dict):
        return 0
    raw = extra.get('prompt_token_accounting')
    if not isinstance(raw, dict):
        return 0
    total = 0
    for key in ('static_prompt_tokens', 'tool_schema_tokens', 'context_packet_tokens'):
        value = raw.get(key)
        if value is None or isinstance(value, bool):
            continue
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            continue
        if parsed > 0:
            total += parsed
    return total


def _last_dynamic_prompt_tokens(state: State | None) -> int:
    """Return measured dynamic prompt tokens, excluding static/tool packet cost."""
    if state is None:
        return 0
    extra = getattr(state, 'extra_data', None)
    if isinstance(extra, dict):
        raw = extra.get('prompt_token_accounting')
        if isinstance(raw, dict):
            value = raw.get('dynamic_history_tokens')
            if value is not None and not isinstance(value, bool):
                try:
                    parsed = int(value)
                except (TypeError, ValueError):
                    parsed = 0
                if parsed > 0:
                    return parsed
    api_tokens = _last_api_prompt_tokens(state)
    if api_tokens <= 0:
        return 0
    return max(0, api_tokens - _fixed_prompt_reserve_tokens(state))


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
