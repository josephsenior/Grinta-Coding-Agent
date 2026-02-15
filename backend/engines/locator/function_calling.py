"""This file contains the function calling implementation for different actions.

This is similar to the functionality of `CodeActResponseParser`.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from backend.core.exceptions import FunctionCallNotExistsError
from backend.core.logger import FORGE_logger as logger
from backend.engines.locator.tools import (
    SearchEntityTool,
    SearchRepoTool,
    create_explore_tree_structure_tool,
)
from backend.engines.orchestrator.function_calling import combine_thought
from backend.engines.orchestrator.tools import create_finish_tool
from backend.engines.common import (
    common_response_to_actions,
)
from backend.events.action import (
    Action,
    CmdRunAction,
    PlaybookFinishAction,
)

if TYPE_CHECKING:
    ChatCompletionToolParam = Any
    ModelResponse = Any


def _create_action_from_tool_call(tool_call, arguments: dict) -> Action:
    """Create appropriate action from tool call."""
    ALL_FUNCTIONS = [
        "explore_tree_structure",
        "search_code_snippets",
        "get_entity_contents",
    ]

    if tool_call.function.name in ALL_FUNCTIONS:
        func_name = tool_call.function.name
        # Convert arguments to JSON string for the python command
        args_json = json.dumps(arguments)
        code = (
            f"import json; "
            f"from backend.runtime.plugins.agent_skills.repo_ops.repo_ops import {func_name}; "
            f"print(json.dumps({func_name}(**json.loads('{args_json}'))))"
        )
        command = f'python3 -c "{code}"'
        logger.debug("TOOL CALL: %s with command: %s", func_name, command)
        return CmdRunAction(command=command)
    if tool_call.function.name == create_finish_tool()["function"]["name"]:
        return PlaybookFinishAction(final_thought=arguments.get("message", ""))
    msg = f"Tool {tool_call.function.name} is not registered. (arguments: {arguments}). Please check the tool name and retry with an existing tool."
    raise FunctionCallNotExistsError(
        msg,
    )


def response_to_actions(
    response: ModelResponse, mcp_tool_names: list[str] | None = None
) -> list[Action]:
    """Convert LLM response to agent actions."""
    return common_response_to_actions(
        response=response,
        create_action_fn=_create_action_from_tool_call,
        combine_thought_fn=combine_thought,
        mcp_tool_names=mcp_tool_names,
    )


def get_tools() -> list[ChatCompletionToolParam]:
    """Get available tools for LOC agent.

    Returns:
        List of tool definitions for function calling

    """
    return [
        create_finish_tool(),
        SearchRepoTool,
        SearchEntityTool,
        create_explore_tree_structure_tool(use_simplified_description=True),
    ]
