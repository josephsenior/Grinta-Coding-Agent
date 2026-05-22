"""Small shared helpers for function-calling tool handlers."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from backend.core.errors import FunctionCallValidationError
from backend.core.logger import app_logger as logger
from backend.engine.tools.security_utils import RISK_LEVELS
from backend.ledger.action import Action, ActionSecurityRisk


def combine_thought(action: Action, thought: str) -> Action:
    """Combine a thought with an existing action's thought."""
    if thought:
        existing = getattr(action, 'thought', None)
        action.thought = f'{thought}\n{existing}' if existing else thought
    return action


def set_security_risk(action: Action, arguments: Mapping[str, Any]) -> None:
    """Set the security risk level for the action."""
    raw = arguments.get('security_risk')
    if raw is None:
        return
    normalized = str(raw).strip().upper()
    if normalized in RISK_LEVELS:
        action.security_risk = getattr(ActionSecurityRisk, normalized)
    else:
        logger.warning('Invalid security_risk value: %s', raw)


def validate_security_risk(arguments: Mapping[str, Any], tool_name: str) -> None:
    """Validate that ``security_risk`` is present and one of ``RISK_LEVELS``.

    Used by tools that mandate an explicit risk label from the model
    (``execute_bash``/``execute_powershell``, ``start_file_edit``, ``browser``).
    Raises :class:`FunctionCallValidationError` on missing or
    invalid value so the failure is surfaced to the model as a tool-call error
    instead of being silently auto-classified server-side. Accepts any case
    (``low``/``LOW``/``Low``) so model output variations don't trip validation.
    """
    raw = arguments.get('security_risk')
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        raise FunctionCallValidationError(
            f'Missing required argument "security_risk" in tool call {tool_name}. '
            f'Provide one of {RISK_LEVELS} based on the action you are about to take.'
        )
    normalized = str(raw).strip().upper()
    if normalized not in RISK_LEVELS:
        raise FunctionCallValidationError(
            f'Invalid "security_risk" value {raw!r} in tool call {tool_name}. '
            f'Must be one of {RISK_LEVELS} (case-insensitive).'
        )


def parse_bool_argument(raw: Any) -> bool:
    """Parse bool-ish tool arguments consistently."""
    return raw is True or (isinstance(raw, str) and raw.lower() == 'true')


def require_tool_argument(
    arguments: Mapping[str, Any], key: str, tool_name: str
) -> Any:
    """Return a required argument value or raise a standardized validation error."""
    if key not in arguments:
        raise FunctionCallValidationError(
            f'Missing required argument "{key}" in tool call {tool_name}'
        )
    return arguments[key]
