"""This file contains the function calling implementation for different actions.

This is similar to the functionality of `CodeActResponseParser`.
"""

from __future__ import annotations

import shlex
from typing import TYPE_CHECKING, Any

from backend.engines.common import (
    FunctionCallNotExistsError,
    FunctionCallValidationError,
    common_response_to_actions,
)
from backend.engines.auditor.tools import (
    create_glob_tool,
    create_grep_tool,
    create_view_tool,
)
from backend.engines.orchestrator.function_calling import combine_thought
from backend.engines.orchestrator.tools import create_finish_tool, create_think_tool
from backend.events.action import (
    Action,
    AgentThinkAction,
    CmdRunAction,
    FileReadAction,
    MCPAction,
    PlaybookFinishAction,
)
from backend.core.enums import FileReadSource

if TYPE_CHECKING:
    ChatCompletionToolParam = Any
    ModelResponse = Any


def grep_to_cmdrun(
    pattern: str, path: str | None = None, include: str | None = None
) -> str:
    """Convert grep tool arguments to a shell command string.

    Args:
        pattern: The regex pattern to search for in file contents
        path: The directory to search in (optional)
        include: Optional file pattern to filter which files to search (e.g., "*.js")

    Returns:
        A properly escaped shell command string for ripgrep

    """
    quoted_pattern = shlex.quote(pattern)
    path_arg = shlex.quote(path) if path else "."
    rg_cmd = f"rg -li {quoted_pattern} --sortr=modified"
    if include:
        quoted_include = shlex.quote(include)
        rg_cmd += f" --glob {quoted_include}"
    complete_cmd = f"{rg_cmd} {path_arg} | head -n 100"
    echo_cmd = f'echo "Below are the execution results of the search command: {complete_cmd}\n"; '
    return echo_cmd + complete_cmd


def glob_to_cmdrun(pattern: str, path: str = ".") -> str:
    """Convert glob tool arguments to a shell command string.

    Args:
        pattern: The glob pattern to match files (e.g., "**/*.js")
        path: The directory to search in (defaults to current directory)

    Returns:
        A properly escaped shell command string for ripgrep implementing glob

    """
    quoted_path = shlex.quote(path)
    quoted_pattern = shlex.quote(pattern)
    rg_cmd = f"rg --files {quoted_path} -g {quoted_pattern} --sortr=modified"
    sort_and_limit_cmd = " | head -n 100"
    complete_cmd = f"{rg_cmd}{sort_and_limit_cmd}"
    echo_cmd = f'echo "Below are the execution results of the glob command: {complete_cmd}\n"; '
    return echo_cmd + complete_cmd


def _create_finish_action(arguments: dict) -> Action:
    """Create a finish action from arguments."""
    return PlaybookFinishAction(final_thought=arguments.get("message", ""))


def _create_view_action(arguments: dict) -> Action:
    """Create a view action from arguments."""
    if "path" not in arguments:
        msg = f'Missing required argument "path" in tool call {create_view_tool()["function"]["name"]}'
        raise FunctionCallValidationError(
            msg,
        )
    return FileReadAction(
        path=arguments["path"],
        impl_source=FileReadSource.FILE_EDITOR,
        view_range=arguments.get("view_range"),
    )


def _create_think_action(arguments: dict) -> Action:
    """Create a think action from arguments."""
    return AgentThinkAction(thought=arguments.get("thought", ""))


def _create_grep_action(arguments: dict) -> Action:
    """Create a grep action from arguments."""
    if "pattern" not in arguments:
        msg = f'Missing required argument "pattern" in tool call {create_grep_tool()["function"]["name"]}'
        raise FunctionCallValidationError(
            msg,
        )

    pattern = arguments["pattern"]
    path = arguments.get("path")
    include = arguments.get("include")
    grep_cmd = grep_to_cmdrun(pattern, path, include)
    return CmdRunAction(command=grep_cmd, is_input=False)


def _create_glob_action(arguments: dict) -> Action:
    """Create a glob action from arguments."""
    if "pattern" not in arguments:
        msg = f'Missing required argument "pattern" in tool call {create_glob_tool()["function"]["name"]}'
        raise FunctionCallValidationError(
            msg,
        )

    pattern = arguments["pattern"]
    path = arguments.get("path", ".")
    glob_cmd = glob_to_cmdrun(pattern, path)
    return CmdRunAction(command=glob_cmd, is_input=False)


def _create_mcp_action(tool_call, arguments: dict) -> Action:
    """Create an MCP action from tool call and arguments."""
    return MCPAction(name=tool_call.function.name, arguments=arguments)


def _create_action_from_tool_call(tool_call: Any, arguments: dict[str, Any]) -> Action:
    """Create an action from a tool call."""
    function_name = tool_call.function.name
    mcp_tool_names = getattr(tool_call, "_mcp_tool_names", None)

    if function_name == create_finish_tool()["function"]["name"]:
        return _create_finish_action(arguments)
    if function_name == create_view_tool()["function"]["name"]:
        return _create_view_action(arguments)
    if function_name == create_think_tool()["function"]["name"]:
        return _create_think_action(arguments)
    if function_name == create_grep_tool()["function"]["name"]:
        return _create_grep_action(arguments)
    if function_name == create_glob_tool()["function"]["name"]:
        return _create_glob_action(arguments)
    if mcp_tool_names and function_name in mcp_tool_names:
        return _create_mcp_action(tool_call, arguments)
    msg = (
        f"Tool {function_name} is not registered. (arguments: {arguments}). "
        "Please check the tool name and retry with an existing tool."
    )
    raise FunctionCallNotExistsError(
        msg,
    )


def response_to_actions(
    response: ModelResponse, mcp_tool_names: list[str] | None = None
) -> list[Action]:
    """Convert model response to actions."""
    return common_response_to_actions(
        response=response,
        create_action_fn=_create_action_from_tool_call,
        combine_thought_fn=combine_thought,
        mcp_tool_names=mcp_tool_names,
    )


def get_tools() -> list[ChatCompletionToolParam]:
    """Get available tools for readonly agent.

    Returns:
        List of tool definitions including Think, Finish, Grep, Glob, and View tools

    """
    return [
        create_think_tool(),
        create_finish_tool(),
        create_grep_tool(),
        create_glob_tool(),
        create_view_tool(),
    ]
