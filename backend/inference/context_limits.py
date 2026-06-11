"""Model context-window limit resolution.

The context window is the provider/model total token window. The usable
prompt/input budget is smaller because output and protocol overhead need room.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

DEFAULT_CONTEXT_OVERHEAD_TOKENS = 4_096
DEFAULT_UNKNOWN_CONTEXT_WINDOW_TOKENS = 200_000

# Cap the output reservation at 25% of the context window so that oversized
# max_output_tokens (e.g. 128K on a 200K window) don't starve the prompt
# budget and trigger compaction far too early.
MAX_OUTPUT_FRACTION = 0.25


@dataclass(frozen=True)
class ModelContextLimits:
    """Resolved model token limits used by prompt budgeting and metrics."""

    context_window_tokens: int | None
    max_output_tokens: int | None
    usable_input_tokens: int | None
    source: str


def derive_usable_input_tokens(
    *,
    context_window_tokens: int | None,
    max_output_tokens: int | None,
    fallback_input_tokens: int | None = None,
    overhead_tokens: int = DEFAULT_CONTEXT_OVERHEAD_TOKENS,
) -> int | None:
    """Derive a safe prompt budget from total context, output, and overhead.

    The output reservation is capped at ``MAX_OUTPUT_FRACTION`` of the context
    window so that models with oversized ``max_output_tokens`` (e.g. 128 K on
    a 200 K window) do not starve the prompt budget and trigger compaction
    far too early.
    """
    context = _positive_int(context_window_tokens)
    output = _positive_int(max_output_tokens) or 0
    fallback = _positive_int(fallback_input_tokens)
    if context is not None:
        capped_output = min(output, int(context * MAX_OUTPUT_FRACTION))
        reserve = max(0, capped_output) + max(0, overhead_tokens)
        return max(1, context - reserve)
    return fallback


def limits_from_catalog(model: str | None) -> ModelContextLimits:
    from backend.inference.catalog_loader import lookup

    if not model:
        return ModelContextLimits(None, None, None, 'unknown_model')
    entry = lookup(model)
    if entry is None:
        return ModelContextLimits(None, None, None, 'uncataloged_model')
    context_window = _positive_int(getattr(entry, 'context_window_tokens', None))
    max_output = _positive_int(getattr(entry, 'max_output_tokens', None))
    max_input = _positive_int(getattr(entry, 'max_input_tokens', None))
    usable = derive_usable_input_tokens(
        context_window_tokens=context_window,
        max_output_tokens=max_output,
        fallback_input_tokens=max_input,
    )
    if context_window is None and max_input is not None and max_output is not None:
        context_window = max_input + max_output
    return ModelContextLimits(
        context_window_tokens=context_window,
        max_output_tokens=max_output,
        usable_input_tokens=usable,
        source='catalog_verified' if getattr(entry, 'verified', False) else 'catalog',
    )


def limits_from_config(
    llm_config: object | None,
    *,
    unknown_default: bool = False,
) -> ModelContextLimits:
    """Resolve context limits from config first, then catalog, then fallback."""
    model = str(getattr(llm_config, 'model', '') or '')
    configured_context = _positive_int(
        getattr(llm_config, 'context_window_tokens', None)
    )
    configured_output = _positive_int(getattr(llm_config, 'max_output_tokens', None))
    configured_input = _positive_int(getattr(llm_config, 'max_input_tokens', None))
    if configured_context is not None:
        usable = derive_usable_input_tokens(
            context_window_tokens=configured_context,
            max_output_tokens=configured_output,
            fallback_input_tokens=configured_input,
        )
        return ModelContextLimits(
            configured_context,
            configured_output,
            usable,
            'config_context_window',
        )

    catalog = limits_from_catalog(model)
    if (
        catalog.context_window_tokens is not None
        or catalog.usable_input_tokens is not None
    ):
        max_output = configured_output or catalog.max_output_tokens
        usable = derive_usable_input_tokens(
            context_window_tokens=catalog.context_window_tokens,
            max_output_tokens=max_output,
            fallback_input_tokens=configured_input or catalog.usable_input_tokens,
        )
        return ModelContextLimits(
            catalog.context_window_tokens,
            max_output,
            usable,
            catalog.source,
        )

    if configured_input is not None:
        context = configured_input + (configured_output or 0)
        return ModelContextLimits(
            context,
            configured_output,
            configured_input,
            'config_max_input',
        )

    if unknown_default:
        usable = derive_usable_input_tokens(
            context_window_tokens=DEFAULT_UNKNOWN_CONTEXT_WINDOW_TOKENS,
            max_output_tokens=configured_output,
        )
        return ModelContextLimits(
            DEFAULT_UNKNOWN_CONTEXT_WINDOW_TOKENS,
            configured_output,
            usable,
            'unknown_default',
        )
    return ModelContextLimits(None, configured_output, None, 'unknown')


def _positive_int(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


__all__ = [
    'DEFAULT_CONTEXT_OVERHEAD_TOKENS',
    'DEFAULT_UNKNOWN_CONTEXT_WINDOW_TOKENS',
    'ModelContextLimits',
    'derive_usable_input_tokens',
    'limits_from_catalog',
    'limits_from_config',
]
