"""Optional wall-clock cap for a single LLM step (``astep``) or one streaming call.

Unset or empty ``FORGE_LLM_STEP_TIMEOUT_SECONDS`` means no cap at the asyncio layer.
Set a positive number to enforce ``asyncio.wait_for`` around slow providers.
Zero or negative is treated as unlimited (same as unset).
"""

from __future__ import annotations

import os


def llm_step_timeout_seconds_from_env() -> float | None:
    """Return timeout in seconds, or ``None`` when no env cap applies."""
    raw = os.getenv("FORGE_LLM_STEP_TIMEOUT_SECONDS", "").strip()
    if not raw:
        return None
    try:
        f = float(raw)
    except ValueError:
        return None
    return None if f <= 0 else f
