"""Hook for recording LLM costs to quota system.

Automatically tracks LLM API costs and reports them to the cost quota middleware.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from backend.core.logger import FORGE_logger as logger
from backend.llm.catalog_loader import get_pricing

if TYPE_CHECKING:
    from backend.core.config import LLMConfig
    from backend.llm.metrics import Metrics


def get_completion_cost(
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    config: LLMConfig | None = None,
) -> float:
    """Calculate the cost of a completion call in USD."""
    # Check for config overrides first
    if config:
        if config.input_cost_per_token is not None and config.output_cost_per_token is not None:
            return (prompt_tokens * config.input_cost_per_token) + (completion_tokens * config.output_cost_per_token)

    prices = get_pricing(model)
    if prices:
        input_cost = (prompt_tokens / 1_000_000) * prices["input"]
        output_cost = (completion_tokens / 1_000_000) * prices["output"]
        return input_cost + output_cost

    logger.debug("No pricing data for model %s — cost reported as $0.00", model)
    return 0.0


def record_llm_cost_from_metrics(user_key: str, metrics: Metrics) -> None:
    """Record LLM cost from metrics object.

    Args:
        user_key: User quota key (user:id or ip:address)
        metrics: LLM metrics object containing cost information

    """
    try:
        from backend.telemetry.cost_recording import record_llm_cost

        # Get accumulated cost from metrics
        if hasattr(metrics, "accumulated_cost"):
            cost = metrics.accumulated_cost
            if cost > 0:
                record_llm_cost(user_key, cost)
                logger.debug("Recorded LLM cost $%.4f for %s", cost, user_key)
    except ImportError:
        # Cost quota middleware not available
        pass
    except Exception as e:
        logger.error("Failed to record LLM cost: %s", e)


def record_llm_cost_from_response(user_key: str, response: dict, model: str, config: LLMConfig | None = None) -> None:
    """Record LLM cost from API response.

    Args:
        user_key: User quota key
        response: LLM API response dict with usage information
        model: Model name used
        config: LLM configuration for cost overrides

    """
    try:
        from backend.telemetry.cost_recording import record_llm_cost

        usage = response.get("usage", {})
        prompt_tokens = usage.get("prompt_tokens", 0)
        completion_tokens = usage.get("completion_tokens", 0)

        cost = get_completion_cost(model, prompt_tokens, completion_tokens, config)

        if cost > 0:
            record_llm_cost(user_key, cost)
            logger.debug("Recorded LLM cost $%.4f for %s using %s", cost, user_key, model)
        else:
            logger.debug(
                "LLM usage for %s using %s: %d prompt, %d completion",
                user_key,
                model,
                prompt_tokens,
                completion_tokens,
            )

    except ImportError:
        pass
    except Exception as e:
        logger.error("Failed to record LLM cost from response: %s", e)
