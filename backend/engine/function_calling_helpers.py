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
    if 'security_risk' in arguments:
        if arguments['security_risk'] in RISK_LEVELS:
            action.security_risk = getattr(
                ActionSecurityRisk, str(arguments['security_risk'])
            )
        else:
            logger.warning(
                'Invalid security_risk value: %s', arguments['security_risk']
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