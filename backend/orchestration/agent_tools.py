"""Agent tool construction helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, NotRequired, TypedDict

from backend.core.logger import app_logger as logger
from backend.inference.tool_types import make_function_chunk, make_tool_param

if TYPE_CHECKING:
    pass


class AgentFunctionChunkArgs(TypedDict):
    name: str
    description: NotRequired[str]
    parameters: NotRequired[dict[str, Any]]
    strict: NotRequired[bool]


def build_tool(tool: dict) -> dict | None:
    """Build a tool parameter from a raw tool dictionary."""
    normalized_tool = dict(tool)
    function_payload = normalized_tool.get('function')
    if not isinstance(function_payload, dict):
        logger.warning('Skipping tool without callable metadata: %s', tool)
        return None

    chunk_kwargs = chunk_args_from_payload(function_payload, tool)
    if chunk_kwargs is None:
        return None

    function_chunk = make_function_chunk_wrapper(chunk_kwargs, tool)
    if function_chunk is None:
        return None

    tool_type = str(normalized_tool.get('type', 'function'))
    tool_param = make_tool_param(function=function_chunk, type=tool_type)
    attach_additional_fields(tool_param, normalized_tool)
    return tool_param


def chunk_args_from_payload(
    function_payload: dict, original_tool: dict
) -> AgentFunctionChunkArgs | None:
    """Extract function chunk arguments from payload."""
    name_value = function_payload.get('name')
    if not isinstance(name_value, str) or not name_value:
        logger.warning('Skipping tool with invalid function name: %s', original_tool)
        return None

    chunk_kwargs: AgentFunctionChunkArgs = {'name': name_value}
    description = function_payload.get('description')
    if isinstance(description, str):
        chunk_kwargs['description'] = description
    parameters = function_payload.get('parameters')
    if isinstance(parameters, dict):
        chunk_kwargs['parameters'] = parameters
    strict = function_payload.get('strict')
    if isinstance(strict, bool):
        chunk_kwargs['strict'] = strict
    return chunk_kwargs


def make_function_chunk_wrapper(
    chunk_kwargs: AgentFunctionChunkArgs, original_tool: dict
):
    """Safely create a function chunk."""
    try:
        return make_function_chunk(**chunk_kwargs)
    except TypeError as exc:
        logger.warning(
            'Skipping tool %s due to invalid function payload: %s',
            original_tool,
            exc,
        )
        return None


def attach_additional_fields(tool_param: dict, normalized_tool: dict) -> None:
    """Attach additional fields to the tool parameter."""
    for extra_key, extra_value in normalized_tool.items():
        if extra_key in {'type', 'function'}:
            continue
        setattr(tool_param, extra_key, extra_value)
