"""Autonomy level enum and normalization (no orchestration deps)."""

from __future__ import annotations

from enum import Enum


class AutonomyLevel(str, Enum):
    """Agent autonomy levels.

    All levels share identical execution, prompting, and retry behaviour.
    The only difference is *when* the agent stops to ask the user before
    running an action:

    - ``CONSERVATIVE``: confirm before every action type in the confirmation flow
      (commands, edits, terminal/browser, MCP, delegation, blackboard writes).
    - ``BALANCED``: ask only for actions classified as high-risk (including MCP).
    - ``FULL``: never ask; the safety validator still blocks forbidden ops.
    """

    CONSERVATIVE = 'conservative'
    BALANCED = 'balanced'
    FULL = 'full'


def normalize_autonomy_level(level: object) -> str:
    """Return the stable string value for an autonomy level."""
    raw = getattr(level, 'value', level)
    text = str(raw or AutonomyLevel.BALANCED.value).strip().lower()
    if '.' in text:
        text = text.rsplit('.', 1)[-1].lower()
    return text


def security_risk_required_for_autonomy(level: object) -> bool:
    """Return whether tool calls must declare ``security_risk``.

    In full autonomy the label does not gate confirmation, so it is optional.
    """
    return normalize_autonomy_level(level) != AutonomyLevel.FULL.value
