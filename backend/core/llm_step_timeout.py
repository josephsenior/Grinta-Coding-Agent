"""Wall-clock cap for a single LLM step (``astep``) or one streaming call.

Unset or empty ``APP_LLM_STEP_TIMEOUT_SECONDS`` falls back to the safe
default (300s) so a hung LLM provider cannot wedge the agent.  Set a
positive number to override; zero or negative is treated as unlimited
(explicit user opt-out).

This default is intentionally conservative: production providers
should return within 5 minutes for any single streaming call.  Hung
sockets, broken keepalives, or provider stalls all surface as
``asyncio.TimeoutError`` in ``action_execution_service`` and become
an ``ErrorObservation`` that the agent can recover from.
"""

from __future__ import annotations

import os

# Production default: 5 minutes per LLM step.  Long enough for a
# genuinely large tool-call response from a non-streaming provider,
# short enough to recover from a hung socket within one user-visible
# poll cycle.  Override via APP_LLM_STEP_TIMEOUT_SECONDS.
DEFAULT_LLM_STEP_TIMEOUT_SECONDS: float = 300.0


def llm_step_timeout_seconds_from_env() -> float | None:
    """Return timeout in seconds, or ``None`` when no env cap applies.

    Returns:
        - A positive float from ``APP_LLM_STEP_TIMEOUT_SECONDS`` if set.
        - ``None`` only if the env var is explicitly set to a non-positive
          value (treated as "unlimited" — the user opt-out escape hatch).
        - :data:`DEFAULT_LLM_STEP_TIMEOUT_SECONDS` (300s) when the env
          var is unset or empty.  This is the production safe default.
    """
    raw = os.getenv('APP_LLM_STEP_TIMEOUT_SECONDS', '').strip()
    if not raw:
        return DEFAULT_LLM_STEP_TIMEOUT_SECONDS
    try:
        f = float(raw)
    except ValueError:
        return DEFAULT_LLM_STEP_TIMEOUT_SECONDS
    if f <= 0:
        return None
    return f


def resolve_step_task_liveness_seconds(
    agent: object | None = None,
    *,
    default_liveness_seconds: float = 600.0,
) -> float:
    """Return the wall-clock cap for a single ``_step_inner`` drain iteration.

    Must cover at least two capped ``astep`` attempts (each may retry once)
    plus time for condensation / message building between attempts.
    """
    if agent is None:
        step_timeout = llm_step_timeout_seconds_from_env()
    else:
        from backend.orchestration.services.action_execution_service import (
            _resolve_llm_step_timeout_seconds,
        )

        step_timeout = _resolve_llm_step_timeout_seconds(agent)

    if step_timeout is None:
        return default_liveness_seconds
    return max(default_liveness_seconds, (2.0 * step_timeout) + 120.0)
