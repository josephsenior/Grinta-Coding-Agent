"""Context budget — boundary token counts for compaction trigger and skip gates."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from backend.context.prompt.prompt_window import (
    estimate_prompt_events_tokens,
    reset_current_tokenizer_model,
    set_current_tokenizer_model,
)
from backend.core.constants import DEFAULT_COMPACTION_RESERVED_SUMMARY_TOKENS
from backend.inference.capabilities.context_limits import limits_from_config
from backend.inference.capabilities.provider_capabilities import model_token_correction

if TYPE_CHECKING:
    from backend.ledger.event import Event
    from backend.orchestration.state.state import State


@dataclass(frozen=True)
class ContextBudget:
    """Token budget for one projected post-boundary event slice."""

    estimated_tokens: int
    effective_window: int
    autocompact_threshold: int
    fixed_prompt_reserve_tokens: int
    reserved_summary_tokens: int

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
        effective_window = _effective_context_window(llm_config)
        fixed_prompt_reserve = _fixed_prompt_reserve_tokens(state)
        reserved_summary = DEFAULT_COMPACTION_RESERVED_SUMMARY_TOKENS
        autocompact_threshold = max(
            1,
            effective_window - reserved_summary - fixed_prompt_reserve
            if effective_window > reserved_summary + fixed_prompt_reserve
            else effective_window,
        )
        boundary_tokens = estimate_boundary_event_tokens(events, llm_config=llm_config)
        return cls(
            estimated_tokens=boundary_tokens,
            effective_window=effective_window,
            autocompact_threshold=autocompact_threshold,
            fixed_prompt_reserve_tokens=fixed_prompt_reserve,
            reserved_summary_tokens=reserved_summary,
        )


def estimate_boundary_event_tokens(
    events: list[Event],
    *,
    llm_config: object | None = None,
) -> int:
    """Tokenizer-accurate count for projected post-boundary events."""
    model_id = str(getattr(llm_config, 'model', '') or '') if llm_config else ''
    model_token = set_current_tokenizer_model(model_id or None)
    try:
        raw = estimate_prompt_events_tokens(events)
    finally:
        reset_current_tokenizer_model(model_token)
    factor, _ = model_token_correction(model_id)
    return int(raw * factor)


def _effective_context_window(llm_config: object | None) -> int:
    limits = limits_from_config(llm_config, unknown_default=True)
    if limits.usable_input_tokens is not None:
        return limits.usable_input_tokens
    return 200_000


def _fixed_prompt_reserve_tokens(state: State | None) -> int:
    if state is None:
        return 0
    extra = getattr(state, 'extra_data', None)
    if not isinstance(extra, dict):
        return 0
    accounting = extra.get('prompt_token_accounting')
    if not isinstance(accounting, dict):
        return 0
    total = 0
    for key in ('static_prompt_tokens', 'tool_schema_tokens', 'context_packet_tokens'):
        value = accounting.get(key)
        if value is None or isinstance(value, bool):
            continue
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            continue
        if parsed > 0:
            total += parsed
    return total


__all__ = [
    'ContextBudget',
    'estimate_boundary_event_tokens',
]
