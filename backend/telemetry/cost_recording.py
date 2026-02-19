"""Cost recording abstraction to avoid server → controller circular dependencies.

Provides a registration pattern where server middleware can register itself as the cost recorder,
and controller/models can record costs without importing server code.
"""

from __future__ import annotations

from collections.abc import Callable

from backend.core.logger import forge_logger as logger

# Global cost recorder callback (registered by server middleware on startup)
_cost_recorder: Callable[[str, float], None] | None = None


def register_cost_recorder(recorder: Callable[[str, float], None]) -> None:
    """Register a cost recorder callback.

    Called by server middleware during initialization to register itself
    as the cost recording backend.

    Args:
        recorder: Callback that accepts (user_key, cost_usd)

    """
    global _cost_recorder
    _cost_recorder = recorder
    logger.debug("Cost recorder registered")


def record_llm_cost(user_key: str, cost: float) -> None:
    """Record LLM cost for a user (layer-agnostic).

    This function can be safely called from any layer (controller, models, etc.)
    without creating circular dependencies. If no cost recorder is registered
    (e.g., in tests or when quota middleware is disabled), this is a no-op.

    Args:
        user_key: User quota key (user:id or ip:address)
        cost: Cost in USD

    """
    if _cost_recorder is None:
        # Cost recording not enabled (quota middleware disabled or not initialized)
        return

    try:
        _cost_recorder(user_key, cost)
    except Exception as exc:
        logger.error("Cost recorder callback failed: %s", exc, exc_info=True)
