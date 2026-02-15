"""Common tool parameter definitions for Orchestrator tools."""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    pass

from backend.engines.orchestrator.tools.security_utils import (
    RISK_LEVELS,
    SECURITY_RISK_DESC,
)


def get_is_input_param(
    description: str = "Whether the command is input to a running process.",
) -> dict[str, Any]:
    """Get a standardized is_input parameter definition.

    Args:
        description: Description of the is_input parameter.

    Returns:
        Parameter definition dictionary.
    """
    return {
        "type": "string",
        "description": description,
        "enum": ["true", "false"],
    }


def get_security_risk_param() -> dict[str, Any]:
    """Get the standard security_risk parameter definition.

    Returns:
        Parameter definition dictionary.
    """
    return {
        "type": "string",
        "description": SECURITY_RISK_DESC,
        "enum": RISK_LEVELS,
    }


def get_command_param(
    description: str, enum: list[str] | None = None
) -> dict[str, Any]:
    """Get the standard command parameter definition.

    Args:
        description: Description of the command parameter.
        enum: Optional list of allowed command values.

    Returns:
        Parameter definition dictionary.
    """
    param: dict[str, Any] = {
        "description": description,
        "type": "string",
    }
    if enum:
        param["enum"] = enum
    return param


def get_url_param(description: str = "The URL to navigate to.") -> dict[str, Any]:
    """Get the standard URL parameter definition.

    Args:
        description: Description of the URL parameter.

    Returns:
        Parameter definition dictionary.
    """
    return {
        "type": "string",
        "description": description,
    }
