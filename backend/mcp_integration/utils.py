"""Utility helpers for configuring and invoking Model Context Protocol clients in Forge."""

from __future__ import annotations

import json
import os
import shutil
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from backend.controller.agent import Agent
    from backend.events.action.mcp import MCPAction
    from backend.events.observation.observation import Observation
    from backend.memory.agent_memory import Memory
    from backend.runtime.base import Runtime
from mcp import McpError

from backend.core.config.mcp_config import (
    MCPConfig,
    MCPServerConfig,
)
from backend.core.logger import forge_logger as logger
from backend.core.pydantic_compat import model_dump_with_options
from backend.events.observation.mcp import MCPObservation
from backend.mcp_integration.cache import get_cached, set_cache
from backend.mcp_integration.client import MCPClient
from backend.mcp_integration.error_collector import mcp_error_collector
from backend.mcp_integration.wrappers import WRAPPER_TOOL_REGISTRY, wrapper_tool_params
from backend.runtime import LocalRuntimeInProcess


def _is_windows_stdio_mcp_disabled() -> bool:
    """Return True when stdio MCP should be bypassed on Windows.

    HTTP/SSE MCP remains enabled by default on Windows.
    """
    return sys.platform == "win32" and not os.getenv("FORGE_ENABLE_WINDOWS_MCP")


def convert_mcps_to_tools(mcps: list[MCPClient] | None) -> list[dict]:
    """Converts a list of MCPClient instances to ChatCompletionToolParam format.

    that can be used by Orchestrator.

    Args:
        mcps: List of MCPClient instances or None

    Returns:
        List of dicts of tools ready to be used by Orchestrator

    """
    if mcps is None:
        logger.warning("mcps is None, returning empty list")
        return []
    all_mcp_tools = []
    try:
        server_tool_names: list[str] = []
        for client in mcps:
            for tool in client.tools:
                mcp_tools = tool.to_param()
                all_mcp_tools.append(mcp_tools)
                server_tool_names.append(tool.name)
        all_mcp_tools.extend(wrapper_tool_params(server_tool_names))
    except Exception as e:
        error_msg = f"Error in convert_mcps_to_tools: {e}"
        logger.error(error_msg)
        mcp_error_collector.add_error(
            server_name="general",
            server_type="conversion",
            error_message=error_msg,
            exception_details=str(e),
        )
        return []
    return all_mcp_tools


async def create_mcps(
    servers: list[MCPServerConfig],
    conversation_id: str | None = None,
) -> list[MCPClient]:
    """Create MCP clients for configured servers.

    Args:
        servers: List of all MCP server configurations
        conversation_id: Optional conversation ID for grouping

    Returns:
        List of successfully connected MCPClient instances
    """
    if not servers:
        return []

    # Connect to each server using appropriate handler
    mcps = []
    for server in servers:
        if client := await _connect_to_server(server, conversation_id):
            mcps.append(client)

    return mcps


async def _connect_to_server(
    server: MCPServerConfig,
    conversation_id: str | None,
) -> MCPClient | None:
    """Connect to a single MCP server based on its type.

    Returns the connected client or None if connection failed.
    """
    if server.type == "stdio":
        return await _connect_stdio_server(server)
    elif server.type in ("sse", "shttp"):
        return await _connect_http_server(server, conversation_id)
    else:
        logger.error("Unknown MCP server type: %s", server.type)
        return None


async def _connect_stdio_server(server: MCPServerConfig) -> MCPClient | None:
    """Connect to an MCP stdio server."""
    # Validate command availability
    if not shutil.which(server.command):
        logger.error(
            'Skipping MCP stdio server "%s": command "%s" not found. '
            "Please install %s or remove this server from your configuration.",
            server.name,
            server.command,
            server.command,
        )
        return None

    logger.info("Initializing MCP agent for %s with stdio connection...", server.name)
    client = MCPClient()

    try:
        await client.connect_stdio(server)
        _log_successful_connection(client, server.name, "STDIO")
        return client
    except Exception as e:
        logger.error("Failed to connect to %s: %s", server.name, str(e), exc_info=True)
        return None


async def _connect_http_server(
    server: MCPServerConfig,
    conversation_id: str | None,
) -> MCPClient | None:
    """Connect to an MCP HTTP-based server (SSE or sHTTP)."""
    connection_type = server.type.upper()

    logger.info(
        "Initializing MCP agent for %s with %s connection...", server.name, connection_type
    )
    client = MCPClient()

    try:
        await client.connect_http(server, conversation_id=conversation_id)
        _log_successful_connection(client, server.url, connection_type)
        return client
    except Exception as e:
        logger.error("Failed to connect to %s: %s", server.url, str(e), exc_info=True)
        return None


def _log_successful_connection(
    client: MCPClient, server_identifier: str, connection_type: str
) -> None:
    """Log successful MCP server connection with tool details."""
    tool_names = [tool.name for tool in client.tools]
    logger.debug(
        "Successfully connected to MCP %s server %s - provides %s tools: %s",
        connection_type,
        server_identifier,
        len(tool_names),
        tool_names,
    )


async def fetch_mcp_tools_from_config(
    mcp_config: MCPConfig,
    conversation_id: str | None = None,
    use_stdio: bool = False,
) -> list[dict]:
    """Retrieves the list of MCP tools from the MCP clients.

    Args:
        mcp_config: The MCP configuration
        conversation_id: Optional conversation ID to associate with the MCP clients
        use_stdio: Whether to use stdio servers for MCP clients, set to True when running from a CLI runtime

    Returns:
        A list of tool dictionaries. Returns an empty list if no connections could be established.

    """
    mcps = []
    mcp_tools = []
    try:
        logger.debug("Creating MCP clients with config: %s", mcp_config)
        
        # Filter servers: only include stdio if use_stdio is True
        servers_to_connect = (
            mcp_config.servers
            if use_stdio
            else [s for s in mcp_config.servers if s.type != "stdio"]
        )
        
        mcps = await create_mcps(servers_to_connect, conversation_id)
        if not mcps:
            logger.warning(
                "No MCP clients were successfully connected; exposing degraded capability status tool only"
            )
            return wrapper_tool_params([])
        mcp_tools = convert_mcps_to_tools(mcps)
    except Exception as e:
        error_msg = f"Error fetching MCP tools: {e!s}"
        logger.error(error_msg)
        mcp_error_collector.add_error(
            server_name="general",
            server_type="fetch",
            error_message=error_msg,
            exception_details=str(e),
        )
        return []
    logger.debug("MCP tools: %s", mcp_tools)
    return mcp_tools


def _serialize_result_to_json(result_dict: dict) -> str:
    """Serialize result dictionary to JSON string with fallbacks."""
    try:
        return json.dumps(result_dict, ensure_ascii=False, default=str)
    except Exception:
        try:
            return repr(result_dict)
        except Exception:
            return '{"error":"unserializable_result"}'


async def _execute_wrapper_tool(
    action: MCPAction, mcps: list[MCPClient]
) -> MCPObservation:
    """Execute a wrapper tool and return observation."""
    try:

        async def _call_underlying(tool_name: str, args: dict):
            from types import SimpleNamespace

            inner_action = SimpleNamespace(name=tool_name, arguments=args)
            return await _call_mcp_raw(mcps, inner_action)

        wrapper_fn = WRAPPER_TOOL_REGISTRY[action.name]
        result_dict = await wrapper_fn(mcps, action.arguments, _call_underlying)
        content_str = _serialize_result_to_json(result_dict)
        return MCPObservation(
            content=content_str, name=action.name, arguments=action.arguments
        )
    except Exception as e:
        logger.error("Wrapper tool %s failed: %s", action.name, e, exc_info=True)
        error_content = json.dumps({"isError": True, "error": str(e), "content": []})
        return MCPObservation(
            content=error_content, name=action.name, arguments=action.arguments
        )


def _find_matching_mcp(mcps: list[MCPClient], action_name: str) -> MCPClient:
    """Find MCP client that supports the requested tool."""
    logger.debug("MCP clients: %s", mcps)
    logger.debug("MCP action name: %s", action_name)

    for client in mcps:
        logger.debug("MCP client tools: %s", client.tools)
        if action_name in [tool.name for tool in client.tools]:
            logger.debug("Matching client: %s", client)
            return client

    msg = f"No matching MCP agent found for tool name: {action_name}"
    raise ValueError(msg)


async def _execute_direct_tool(
    action: MCPAction, matching_client: MCPClient
) -> MCPObservation:
    """Execute a direct MCP tool call and return observation."""
    try:
        if cached := get_cached(action.name, action.arguments):
            logger.debug("Cache hit for MCP tool %s", action.name)
            return MCPObservation(
                content=json.dumps(cached), name=action.name, arguments=action.arguments
            )

        # Call tool
        response = await matching_client.call_tool(action.name, action.arguments)
        logger.debug("MCP response: %s", response)
        result_dict = model_dump_with_options(response, mode="json")

        # Cache result
        try:
            set_cache(action.name, action.arguments, result_dict)
        except Exception as cache_exc:
            logger.debug("Cache set skipped for %s: %s", action.name, cache_exc)

        # Serialize and return
        content_json = _serialize_result_to_json(result_dict)
        return MCPObservation(
            content=content_json, name=action.name, arguments=action.arguments
        )
    except McpError as e:
        logger.error("MCP error when calling tool %s: %s", action.name, e)
        error_content = (
            f"MCP tool '{action.name}' returned an error: {e}\n"
            "You can try:\n"
            "  1. Re-call the tool with corrected arguments\n"
            "  2. Use bash (execute_bash) as a fallback to accomplish the same task\n"
            "  3. Use mcp_capabilities_status to check current MCP server health"
        )
        return MCPObservation(
            content=error_content, name=action.name, arguments=action.arguments
        )
    except Exception as e:
        # Catch-all for connection failures, timeouts, and unexpected errors
        logger.error(
            "MCP tool '%s' failed unexpectedly: %s", action.name, e, exc_info=True
        )
        error_content = (
            f"MCP server for tool '{action.name}' is unavailable (reason: {type(e).__name__}: {e}).\n"
            "The MCP server may be disconnected or experiencing issues.\n"
            "Fallback options:\n"
            "  1. Use bash (execute_bash) to accomplish the same task\n"
            "  2. Use mcp_capabilities_status to inspect current MCP availability\n"
            "  3. Continue with non-MCP tools"
        )
        return MCPObservation(
            content=error_content, name=action.name, arguments=action.arguments
        )


async def call_tool_mcp(mcps: list[MCPClient], action: MCPAction) -> Observation:
    """Call a tool on an MCP server and return the observation.

    Args:
        mcps: The list of MCP clients to execute the action on
        action: The MCP action to execute

    Returns:
        The observation from the MCP server

    """
    from backend.events.observation import ErrorObservation

    logger.debug("MCP action received: %s", action)

    # Handle wrapper tools
    if action.name in WRAPPER_TOOL_REGISTRY:
        return await _execute_wrapper_tool(action, mcps)

    if not mcps:
        return ErrorObservation(
            "No MCP clients are currently connected. "
            "Use mcp_capabilities_status to inspect availability and continue with non-MCP tools."
        )

    # Handle direct tools with graceful fallback on client lookup failure
    try:
        matching_client = _find_matching_mcp(mcps, action.name)
    except ValueError:
        return ErrorObservation(
            f"MCP tool '{action.name}' is not available on any connected MCP server.\n"
            "This may mean the server that provides this tool is disconnected.\n"
            "Use mcp_capabilities_status to check which tools are currently available, "
            "or use bash (execute_bash) as a fallback."
        )
    return await _execute_direct_tool(action, matching_client)


async def _call_mcp_raw(mcps: list[MCPClient], action) -> dict:
    matching_client = next(
        (
            client
            for client in mcps
            if action.name in [tool.name for tool in client.tools]
        ),
        None,
    )
    if not matching_client:
        msg = f"Underlying tool {action.name} not found for wrapper"
        raise ValueError(msg)
    if cached := get_cached(action.name, action.arguments):
        return cached
    response = await matching_client.call_tool(action.name, action.arguments)
    result_dict = model_dump_with_options(response, mode="json")
    set_cache(action.name, action.arguments, result_dict)
    return result_dict


async def add_mcp_tools_to_agent(
    agent: Agent, runtime: Runtime, memory: Memory
) -> MCPConfig | None:
    """Add MCP tools to an agent."""
    assert runtime.runtime_initialized, (
        "Runtime must be initialized before adding MCP tools"
    )
    extra_servers = []
    playbook_mcp_configs = memory.get_playbook_mcp_tools()
    for mcp_config in playbook_mcp_configs:
        # Convert playbook servers to unified format
        for server in mcp_config.servers:
            if server not in extra_servers:
                extra_servers.append(server)
                logger.warning("Added playbook MCP server: %s (%s)", server.name, server.type)
    
    updated_mcp_config = runtime.get_mcp_config(extra_servers)

    mcp_tools = await fetch_mcp_tools_from_config(
        updated_mcp_config,
        use_stdio=isinstance(runtime, LocalRuntimeInProcess),
    )
    tool_names = [tool["function"]["name"] for tool in mcp_tools]
    logger.info("Loaded %s MCP tools: %s", len(mcp_tools), tool_names)
    agent.set_mcp_tools(mcp_tools)
    return updated_mcp_config
