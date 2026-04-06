"""Hook for recording LLM costs to quota system.

Automatically tracks LLM API costs and reports them to the cost quota middleware.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from backend.core.logger import app_logger as logger
from backend.inference.catalog_loader import get_pricing

if TYPE_CHECKING:
    from backend.core.config import LLMConfig
    from backend.inference.metrics import Metrics


def get_completion_cost(
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    config: LLMConfig | None = None,
) -> float:
    """Calculate the cost of a completion call in USD."""
    # Check for config overrides first
    if config:
        if (
            config.input_cost_per_token is not None
            and config.output_cost_per_token is not None
        ):
            return (prompt_tokens * config.input_cost_per_token) + (
                completion_tokens * config.output_cost_per_token
            )

    prices = get_pricing(model)
    if prices:
        input_cost = (prompt_tokens / 1_000_000) * prices['input']
        output_cost = (completion_tokens / 1_000_000) * prices['output']
        return input_cost + output_cost

    logger.debug('No pricing data for model %s — cost reported as $0.00', model)
    return 0.0


def record_llm_cost_from_metrics(user_key: str, metrics: Metrics) -> None:
    """Log LLM cost from a metrics object.

    Args:
        user_key: User quota key (user:id or ip:address)
        metrics: LLM metrics object containing cost information

    """
    if not hasattr(metrics, 'accumulated_cost'):
        return

    cost = metrics.accumulated_cost
    if cost > 0:
        logger.debug('LLM cost for %s: $%.4f', user_key, cost)


def record_llm_cost_from_response(
    user_key: str, response: dict, model: str, config: LLMConfig | None = None
) -> None:
    """Log LLM cost derived from an API response.

    Args:
        user_key: User quota key
        response: LLM API response dict with usage information
        model: Model name used
        config: LLM configuration for cost overrides

    """
    usage = response.get('usage', {})
    prompt_tokens = usage.get('prompt_tokens', 0)
    completion_tokens = usage.get('completion_tokens', 0)

    cost = get_completion_cost(model, prompt_tokens, completion_tokens, config)

    if cost > 0:
        logger.debug('LLM cost for %s using %s: $%.4f', user_key, model, cost)
    else:
        logger.debug(
            'LLM usage for %s using %s: %d prompt, %d completion',
            user_key,
            model,
            prompt_tokens,
            completion_tokens,
        )
