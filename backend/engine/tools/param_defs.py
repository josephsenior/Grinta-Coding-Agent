"""Common tool parameter definitions for Orchestrator tools."""

from __future__ import annotations

import copy
from typing import TYPE_CHECKING, Any

from backend.core.autonomy import security_risk_required_for_autonomy
from backend.core.constants import (
    RISK_LEVELS,
    SECURITY_RISK_DESC,
)
from backend.inference.tool_support.tool_types import (
    make_function_chunk,
    make_tool_param,
)

if TYPE_CHECKING:
    from backend.engine.contracts import ChatCompletionToolParam


def create_tool_definition(
    name: str,
    description: str,
    properties: dict[str, Any],
    required: list[str],
    additional_properties: bool = False,
) -> ChatCompletionToolParam:
    """Create a standardized tool definition."""
    return make_tool_param(
        type='function',
        function=make_function_chunk(
            name=name,
            description=description,
            parameters={
                'type': 'object',
                'properties': properties,
                'required': required,
                'additionalProperties': additional_properties,
            },
        ),
    )


def get_is_input_param(
    description: str = 'Whether the command is input to a running process.',
) -> dict[str, Any]:
    """Get a standardized is_input parameter definition.

    Args:
        description: Description of the is_input parameter.

    Returns:
        Parameter definition dictionary.
    """
    return {
        'type': 'string',
        'description': description,
        'enum': ['true', 'false'],
    }


def get_security_risk_param() -> dict[str, Any]:
    """Get the standard security_risk parameter definition.

    Returns:
        Parameter definition dictionary.
    """
    return {
        'type': 'string',
        'description': SECURITY_RISK_DESC,
        'enum': RISK_LEVELS,
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
        'description': description,
        'type': 'string',
    }
    if enum:
        param['enum'] = enum
    return param


def get_url_param(description: str = 'The URL to navigate to.') -> dict[str, Any]:
    """Get the standard URL parameter definition.

    Args:
        description: Description of the URL parameter.

    Returns:
        Parameter definition dictionary.
    """
    return {
        'type': 'string',
        'description': description,
    }


def get_path_param(description: str) -> dict[str, Any]:
    """Get the standard path parameter definition.

    Args:
        description: Description of the path parameter.

    Returns:
        Parameter definition dictionary.
    """
    return {
        'type': 'string',
        'description': description,
    }


def get_timeout_param(description: str) -> dict[str, Any]:
    """Get the standard timeout parameter definition.

    Args:
        description: Description of the timeout parameter.

    Returns:
        Parameter definition dictionary.
    """
    return {
        'type': 'number',
        'description': description,
    }


def _relax_security_risk_in_parameters(parameters: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of *parameters* with ``security_risk`` no longer required."""
    params = copy.deepcopy(parameters)
    required = list(params.get('required') or [])
    if 'security_risk' in required:
        params['required'] = [name for name in required if name != 'security_risk']
    for clause in list(params.get('allOf') or []):
        if not isinstance(clause, dict):
            continue
        then = clause.get('then')
        if not isinstance(then, dict):
            continue
        then_required = list(then.get('required') or [])
        if 'security_risk' in then_required:
            then['required'] = [
                name for name in then_required if name != 'security_risk'
            ]
    return params


def relax_security_risk_in_tool(tool: ChatCompletionToolParam) -> ChatCompletionToolParam:
    """Make ``security_risk`` optional in a single tool schema."""
    relaxed = copy.deepcopy(tool)
    function = relaxed.get('function')
    if not isinstance(function, dict):
        return relaxed
    parameters = function.get('parameters')
    if not isinstance(parameters, dict):
        return relaxed
    function['parameters'] = _relax_security_risk_in_parameters(parameters)
    return relaxed


def relax_security_risk_in_tools(
    tools: list[ChatCompletionToolParam],
    autonomy_level: object,
) -> list[ChatCompletionToolParam]:
    """Drop ``security_risk`` from required lists when autonomy is full."""
    if security_risk_required_for_autonomy(autonomy_level):
        return tools
    return [relax_security_risk_in_tool(tool) for tool in tools]


__all__ = [
    'create_tool_definition',
    'get_command_param',
    'get_is_input_param',
    'get_path_param',
    'get_security_risk_param',
    'get_timeout_param',
    'get_url_param',
    'relax_security_risk_in_tool',
    'relax_security_risk_in_tools',
]
