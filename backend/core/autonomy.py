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


_VALID_AUTONOMY_LEVELS = frozenset(
    {
        AutonomyLevel.CONSERVATIVE.value,
        AutonomyLevel.BALANCED.value,
        AutonomyLevel.FULL.value,
    }
)


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


def resolve_persisted_autonomy_level(raw: object) -> str:
    """Normalize a persisted settings value."""
    return normalize_autonomy_level(raw)


def autonomy_runtime_notice(level: object) -> str:
    """Short user-facing note after an autonomy change."""
    normalized = normalize_autonomy_level(level)
    risk_note = (
        'security_risk is optional on shell and file-write tools.'
        if normalized == AutonomyLevel.FULL.value
        else 'security_risk is required on shell and file-write tools.'
    )
    if normalized == AutonomyLevel.FULL.value:
        return f'Autonomy set to full: no confirmation prompts; {risk_note}'
    if normalized == AutonomyLevel.CONSERVATIVE.value:
        return (
            'Autonomy set to conservative: confirmation before shell, edits, '
            f'terminal, browser, MCP, and delegation actions; {risk_note}'
        )
    return (
        'Autonomy set to balanced: confirmation for high-risk actions only; '
        f'{risk_note}'
    )
