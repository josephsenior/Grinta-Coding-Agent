"""Optional wall-clock cap for a single LLM step (``astep``).

Unset or empty ``APP_LLM_STEP_TIMEOUT_SECONDS`` leaves the step uncapped.
Set a positive number to opt into an outer wall-clock cap; zero or negative
also means uncapped.

Streaming calls have their own first-chunk and per-chunk stall timeouts in the
executor.  A blind whole-step cap is not progress-aware, so it must stay
opt-in; otherwise it can kill a healthy long reasoning/tool-call stream before
the provider finalizes the response.
"""

from __future__ import annotations

import os

# No production default for the outer step cap. Streaming liveness is handled
# by first-chunk/per-chunk timeouts, which are progress-aware.
DEFAULT_LLM_STEP_TIMEOUT_SECONDS: float | None = None


def llm_step_timeout_seconds_from_env() -> float | None:
    """Return timeout in seconds, or ``None`` when no env cap applies.

    Returns:
        - A positive float from ``APP_LLM_STEP_TIMEOUT_SECONDS`` if set.
        - ``None`` if unset, empty, invalid, zero, or negative.
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
