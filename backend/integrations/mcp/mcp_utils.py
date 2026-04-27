"""Utility helpers for configuring and invoking Model Context Protocol clients in App."""

from __future__ import annotations

import asyncio
import copy
import json
import os
import re
import shutil
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import quote

if TYPE_CHECKING:
    from backend.context.agent_memory import Memory
    from backend.execution.base import Runtime
    from backend.ledger.action.mcp import MCPAction
    from backend.ledger.observation.observation import Observation
    from backend.orchestration.agent import Agent

from mcp import McpError

from backend.core.config.mcp_config import (
    MCPConfig,
    MCPServerConfig,
)
from backend.core.logger import app_logger as logger
from backend.core.pydantic_compat import model_dump_with_options
from backend.execution import LocalRuntimeInProcess
from backend.integrations.mcp.cache import get_cached, set_cache
from backend.integrations.mcp.client import MCPClient
from backend.integrations.mcp.error_collector import mcp_error_collector
from backend.integrations.mcp.mcp_bootstrap_status import (
    MCPBootstrapStatus,
    get_mcp_bootstrap_status,
    set_mcp_bootstrap_status,
)
from backend.integrations.mcp.wrappers import (
    WRAPPER_TOOL_REGISTRY,
    wrapper_tool_params,
)
from backend.ledger.observation.mcp import MCPObservation

# Populated by ``convert_mcps_to_tools`` for the current fetch cycle (cleared in ``fetch_mcp_tools_from_config``).
_last_mcp_conversion_errors: list[str] = []


def _get_mcp_connect_timeout_sec() -> float:
    """Return MCP server connect timeout in seconds.

    Default is generous for cold ``npx``/``uvx`` first installs; override with
    ``APP_MCP_CONNECT_TIMEOUT_SEC``.
    """
    raw = os.getenv('APP_MCP_CONNECT_TIMEOUT_SEC', '60')
    try:
        timeout = float(raw)
        return timeout if timeout > 0 else 60.0
    except (TypeError, ValueError):
        return 60.0


_ENV_VAR_PATTERN = re.compile(r'^\$\{([A-Za-z_][A-Za-z0-9_]*)\}$')


def _resolve_server_env(raw_env: dict[str, Any] | None) -> dict[str, str] | None:
    """Resolve MCP server env values against ``os.environ``.

    Rules (applied per key/value):
      * ``""`` (empty)        -> look up ``os.environ[key]``. If missing, drop
        the key so the parent process env (already inherited by the stdio
        transport) is used and we don't pass a literal empty string, which
        some MCP servers (e.g. ``@modelcontextprotocol/server-github``) treat
        as an auth failure.
      * ``"${VAR}"``          -> look up ``os.environ["VAR"]``. If missing,
        drop the key (same rationale).
      * anything else         -> passed through verbatim.

    **GitHub MCP:** Set **`GITHUB_PERSONAL_ACCESS_TOKEN`** in ``.env`` (same
    name the server reads). The bundled config uses an empty placeholder;
    we resolve it from ``os.environ`` like any other key—**``GITHUB_TOKEN`` is
    not consulted.**

    **``${PROJECT_ROOT}``:** If the variable is unset, uses
    :func:`backend.core.workspace_resolution.get_effective_workspace_root`
    (same order as the CLI: env, settings, cwd), then ``os.getcwd()`` so MCP
    children like Rigour always receive a concrete path.
    """
    if raw_env is None:
        return None
    if len(raw_env) == 0:
        return {}

    resolved: dict[str, str] = {}
    for key, value in raw_env.items():
        if not isinstance(value, str):
            resolved[key] = str(value)
            continue

        if value == '':
            from_env = os.environ.get(key)
            if from_env:
                resolved[key] = from_env
            continue

        match = _ENV_VAR_PATTERN.match(value.strip())
        if match is None:
            resolved[key] = value
            continue

        var_name = match.group(1)
        from_env = os.environ.get(var_name)
        if from_env:
            resolved[key] = from_env
            continue
        if var_name == 'PROJECT_ROOT':
            from backend.core.workspace_resolution import (
                get_effective_workspace_root,
            )

            eff = get_effective_workspace_root()
            if eff is not None:
                resolved[key] = str(eff.resolve())
            else:
                try:
                    resolved[key] = str(Path.cwd().resolve())
                except OSError:
                    pass
        continue

    return resolved


def _apply_exa_mcp_url_auth(server: MCPServerConfig) -> MCPServerConfig:
    """Align hosted Exa MCP with OpenCode: auth via ``exaApiKey`` query parameter.

    Exa documents ``https://mcp.exa.ai/mcp?exaApiKey=...``. Grinta's HTTP MCP
    client also sends ``Authorization: Bearer`` when ``api_key`` is set; Exa
    expects the query form, so we fold ``api_key`` / ``EXA_API_KEY`` into the
    URL and clear ``api_key`` to avoid conflicting headers.
    """
    if server.type not in ('sse', 'shttp') or not server.url:
        return server
    if 'mcp.exa.ai' not in server.url:
        return server
    if 'exaApiKey=' in server.url:
        return server
    key = (server.api_key or '').strip()
    if not key:
        key = (os.environ.get('EXA_API_KEY') or '').strip()
    if not key:
        return server
    sep = '&' if '?' in server.url else '?'
    new_url = f'{server.url}{sep}exaApiKey={quote(key, safe="")}'
    return server.model_copy(update={'url': new_url, 'api_key': None})


def convert_mcps_to_tools(mcps: list[MCPClient] | None) -> list[dict]:
    """Converts a list of MCPClient instances to ChatCompletionToolParam format.

    that can be used by Orchestrator.

    Args:
        mcps: List of MCPClient instances or None

    Returns:
        List of dicts of tools ready to be used by Orchestrator

    """
    if mcps is None:
        logger.warning('mcps is None, returning empty list')
        return []
    global _last_mcp_conversion_errors
    _last_mcp_conversion_errors = []
    all_mcp_tools: list[dict] = []
    server_tool_names: list[str] = []
    conversion_errors: list[str] = []

    for client in mcps:
        try:
            tools_iter = getattr(client, 'tools', None) or []
            tools_list = list(tools_iter)
        except Exception as e:
            err = f'list client tools: {e}'
            conversion_errors.append(err)
            logger.error('convert_mcps_to_tools: %s', err, exc_info=True)
            mcp_error_collector.add_error(
                server_name='general',
                server_type='conversion',
                error_message=err,
                exception_details=str(e),
            )
            continue

        for tool in tools_list:
            try:
                mcp_tools = tool.to_param()
                all_mcp_tools.append(mcp_tools)
                server_tool_names.append(tool.name)
            except Exception as e:
                tname = getattr(tool, 'name', '<unknown>')
                err = f'tool {tname!r} to_param: {e}'
                conversion_errors.append(err)
                logger.error('convert_mcps_to_tools: %s', err, exc_info=True)
                mcp_error_collector.add_error(
                    server_name='general',
                    server_type='conversion',
                    error_message=err,
                    exception_details=str(e),
                )

    try:
        all_mcp_tools.extend(wrapper_tool_params(server_tool_names))
    except Exception as e:
        err = f'wrapper_tool_params: {e}'
        conversion_errors.append(err)
        logger.error('convert_mcps_to_tools: %s', err, exc_info=True)
        mcp_error_collector.add_error(
            server_name='general',
            server_type='conversion',
            error_message=err,
            exception_details=str(e),
        )

    _last_mcp_conversion_errors = conversion_errors
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

    # Connect to servers in parallel so one slow server does not stall
    # overall MCP bootstrap for the conversation.
    connect_tasks = [_connect_to_server(server, conversation_id) for server in servers]
    results = await asyncio.gather(*connect_tasks)
    return [client for client in results if client is not None]


async def _connect_to_server(
    server: MCPServerConfig,
    conversation_id: str | None,
) -> MCPClient | None:
    """Connect to a single MCP server based on its type.

    Returns the connected client or None if connection failed.
    """
    if server.type == 'stdio':
        return await _connect_stdio_server(server)
    if server.type in ('sse', 'shttp'):
        return await _connect_http_server(server, conversation_id)
    logger.error('Unknown MCP server type: %s', server.type)
    return None


async def _connect_stdio_server(server: MCPServerConfig) -> MCPClient | None:
    """Connect to an MCP stdio server."""
    # Validate command availability
    if not server.command or not shutil.which(server.command):
        logger.error(
            'Skipping MCP stdio server "%s": command "%s" not found. '
            'Please install %s or remove this server from your configuration.',
            server.name,
            server.command,
            server.command,
        )
        return None

    logger.info('Initializing MCP agent for %s with stdio connection...', server.name)
    client = MCPClient()
    timeout_sec = _get_mcp_connect_timeout_sec()

    # Swap empty / ${VAR} env entries with real values from os.environ so
    # secrets defined in the user's .env (e.g. GITHUB_PERSONAL_ACCESS_TOKEN)
    # actually reach the MCP child process.
    resolved_env = _resolve_server_env(server.env)
    if resolved_env is not server.env:
        server = server.model_copy(update={'env': resolved_env})

    if server.name == 'rigour':
        from backend.integrations.mcp.rigour_bootstrap import (
            ensure_minimal_rigour_yml_for_mcp,
        )

        ensure_minimal_rigour_yml_for_mcp(resolved_env if resolved_env else server.env)

    try:
        await asyncio.wait_for(client.connect_stdio(server), timeout=timeout_sec)
        _log_successful_connection(client, server.name, 'STDIO')
        return client
    except TimeoutError:
        logger.warning(
            "Timed out connecting to stdio MCP server '%s' after %.1fs; skipping.",
            server.name,
            timeout_sec,
        )
        return None
    except Exception as e:
        logger.error('Failed to connect to %s: %s', server.name, str(e), exc_info=True)
        return None


async def _connect_http_server(
    server: MCPServerConfig,
    conversation_id: str | None,
) -> MCPClient | None:
    """Connect to an MCP HTTP-based server (SSE or sHTTP)."""
    connection_type = server.type.upper()

    logger.info(
        'Initializing MCP agent for %s with %s connection...',
        server.name,
        connection_type,
    )
    client = MCPClient()
    timeout_sec = _get_mcp_connect_timeout_sec()

    try:
        server = _apply_exa_mcp_url_auth(server)
        await asyncio.wait_for(
            client.connect_http(server, conversation_id=conversation_id),
            timeout=timeout_sec,
        )
        _log_successful_connection(client, server.url or '', connection_type)
        return client
    except TimeoutError:
        logger.warning(
            "Timed out connecting to %s MCP server '%s' after %.1fs; skipping.",
            connection_type,
            server.name,
            timeout_sec,
        )
        return None
    except Exception as e:
        logger.error('Failed to connect to %s: %s', server.url, str(e), exc_info=True)
        return None


def _log_successful_connection(
    client: MCPClient, server_identifier: str, connection_type: str
) -> None:
    """Log successful MCP server connection with tool details."""
    tool_names = [tool.name for tool in client.tools]
    logger.debug(
        'Successfully connected to MCP %s server %s - provides %s tools: %s',
        connection_type,
        server_identifier,
        len(tool_names),
        tool_names,
    )


async def fetch_mcp_tools_from_config(
    mcp_config: MCPConfig,
    conversation_id: str | None = None,
    use_stdio: bool = False,
    reserved_tool_names: frozenset[str] | None = None,
) -> list[dict]:
    """Retrieves the list of MCP tools from the MCP clients.

    Args:
        mcp_config: The MCP configuration
        conversation_id: Optional conversation ID to associate with the MCP clients
        use_stdio: Whether to use stdio servers for MCP clients, set to True when running from a CLI runtime
        reserved_tool_names: Optional names already claimed so MCP aliases avoid collisions

    Returns:
        A list of tool dictionaries. Returns an empty list if no connections could be established.

    """
    global _last_mcp_conversion_errors
    _last_mcp_conversion_errors = []

    if not getattr(mcp_config, 'enabled', False):
        set_mcp_bootstrap_status(
            MCPBootstrapStatus(
                state='mcp_disabled',
                mcp_enabled=False,
                configured_server_count=len(mcp_config.servers or []),
            )
        )
        return []

    # Filter servers: only include stdio if use_stdio is True
    servers_to_connect = (
        mcp_config.servers
        if use_stdio
        else [s for s in mcp_config.servers if s.type != 'stdio']
    )
    configured_n = len(mcp_config.servers or [])
    attempted_n = len(servers_to_connect)

    if configured_n == 0:
        set_mcp_bootstrap_status(
            MCPBootstrapStatus(
                state='no_servers_configured',
                mcp_enabled=True,
                configured_server_count=0,
                attempted_server_count=0,
            )
        )
        return []

    mcps: list[MCPClient] = []
    mcp_tools: list[dict] = []
    try:
        logger.debug('Creating MCP clients with config: %s', mcp_config)

        mcps = await create_mcps(servers_to_connect, conversation_id)
        if not mcps:
            logger.warning(
                'No MCP clients were successfully connected; exposing degraded capability status tool only'
            )
            set_mcp_bootstrap_status(
                MCPBootstrapStatus(
                    state='no_clients_connected',
                    mcp_enabled=True,
                    configured_server_count=configured_n,
                    attempted_server_count=attempted_n,
                    connected_client_count=0,
                    remote_tool_param_count=0,
                )
            )
            return wrapper_tool_params([])

        from backend.integrations.mcp.mcp_bootstrap_status import (
            MCPBootstrapState,
        )
        from backend.integrations.mcp.mcp_tool_aliases import (
            prepare_mcp_tool_exposed_names,
        )

        reserved = set(reserved_tool_names or ()) | set(
            getattr(mcp_config, 'mcp_exposed_name_reserved', frozenset()) or frozenset()
        )
        prepare_mcp_tool_exposed_names(mcps, reserved)
        mcp_tools = convert_mcps_to_tools(mcps)
        remote_tool_count = sum(len(getattr(c, 'tools', ()) or ()) for c in mcps)
        conv_errs = list(_last_mcp_conversion_errors)
        boot_state: MCPBootstrapState
        if remote_tool_count == 0:
            boot_state = 'connected_no_remote_tools'
        elif conv_errs:
            boot_state = 'partial_tool_conversion'
        else:
            boot_state = 'healthy'
        set_mcp_bootstrap_status(
            MCPBootstrapStatus(
                state=boot_state,
                mcp_enabled=True,
                configured_server_count=configured_n,
                attempted_server_count=attempted_n,
                connected_client_count=len(mcps),
                remote_tool_param_count=remote_tool_count,
                conversion_errors=conv_errs,
                last_error=conv_errs[-1] if conv_errs else None,
            )
        )
    except Exception as e:
        error_msg = f'Error fetching MCP tools: {e!s}'
        logger.error(error_msg)
        mcp_error_collector.add_error(
            server_name='general',
            server_type='fetch',
            error_message=error_msg,
            exception_details=str(e),
        )
        set_mcp_bootstrap_status(
            MCPBootstrapStatus(
                state='fetch_failed',
                mcp_enabled=True,
                configured_server_count=configured_n,
                attempted_server_count=attempted_n,
                connected_client_count=0,
                last_error=str(e),
            )
        )
        # Degraded but explicit: keep diagnostics wrapper tools so the agent/UI can see state.
        return wrapper_tool_params([])
    finally:
        # Probe clients are only used to list tools; keeping them alive orphans fastmcp tasks
        # (stdio/session runners) and triggers "Task was destroyed but it is pending".
        # Sequential teardown: parallel gather races stdio subprocess shutdown on Windows
        # and can leave _stdio_transport_connect_task to finish later with
        # "Task exception was never retrieved".
        if mcps:
            for c in mcps:
                try:
                    await c.disconnect()
                except asyncio.CancelledError:
                    raise
                except (
                    BaseExceptionGroup
                ) as eg:  # noqa: F821  # pylint: disable=undefined-variable
                    logger.debug('MCP probe disconnect (exception group): %s', eg)
                except Exception as e:
                    logger.debug('MCP probe disconnect: %s', e, exc_info=True)
                await asyncio.sleep(0)
            await asyncio.sleep(0.05)
    logger.debug('MCP tools: %s', mcp_tools)
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


def _normalize_mcp_success_payload(result_dict: dict) -> dict:
    """Attach stable success metadata without discarding existing payload fields."""
    payload = dict(result_dict)
    is_error = bool(payload.get('isError')) or payload.get('ok') is False
    payload['ok'] = not is_error
    payload['isError'] = is_error
    payload.setdefault('retryable', False)
    return payload


def _build_mcp_error_payload(
    *,
    action_name: str,
    message: str,
    code: str,
    retryable: bool,
) -> dict:
    """Build a stable MCP error envelope."""
    return {
        'ok': False,
        'isError': True,
        'error': message,
        'error_code': code,
        'retryable': retryable,
        'tool': action_name,
        'content': [],
    }


def _looks_like_mcp_validation_error(message: str) -> bool:
    """Return True when MCP error text indicates argument/schema mismatch."""
    text = (message or '').lower()
    return any(
        marker in text
        for marker in (
            '-32602',
            'input validation error',
            'invalid arguments',
            'invalid_type',
            'validation error',
        )
    )


def _coerce_value_to_schema(value: Any, schema: dict[str, Any]) -> tuple[Any, bool]:
    """Best-effort coercion for common JSON schema field types."""
    expected = schema.get('type')

    if expected == 'string':
        if isinstance(value, str):
            return value, False
        if isinstance(value, (dict, list)):
            return json.dumps(value, ensure_ascii=False), True
        return str(value), True

    if expected == 'array':
        if isinstance(value, list):
            return value, False
        if isinstance(value, (tuple, set)):
            return list(value), True
        return [value], True

    if expected == 'object':
        if isinstance(value, dict):
            return value, False
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
                if isinstance(parsed, dict):
                    return parsed, True
            except Exception:
                pass
        return value, False

    if expected == 'integer':
        if isinstance(value, bool):
            return int(value), True
        if isinstance(value, int):
            return value, False
        if isinstance(value, float):
            return (int(value), True) if value.is_integer() else (value, False)
        if isinstance(value, str):
            try:
                return int(value.strip()), True
            except Exception:
                return value, False
        return value, False

    if expected == 'number':
        if isinstance(value, bool):
            return float(int(value)), True
        if isinstance(value, float):
            return value, False
        if isinstance(value, int):
            return float(value), True
        if isinstance(value, str):
            try:
                return float(value.strip()), True
            except Exception:
                return value, False
        return value, False

    if expected == 'boolean':
        if isinstance(value, bool):
            return value, False
        if isinstance(value, str):
            s = value.strip().lower()
            if s in {'true', '1', 'yes', 'y', 'on'}:
                return True, True
            if s in {'false', '0', 'no', 'n', 'off'}:
                return False, True
            return value, False
        if isinstance(value, (int, float)):
            return bool(value), True
        return value, False

    return value, False


def _repair_args_with_schema(
    args: dict[str, Any], input_schema: dict[str, Any] | None
) -> tuple[dict[str, Any], bool]:
    """Repair argument types against the MCP tool's declared input schema."""
    if input_schema is None or not isinstance(input_schema, dict):
        return args, False

    properties = input_schema.get('properties')
    if not isinstance(properties, dict) or len(properties) == 0:
        return args, False

    repaired = copy.deepcopy(args)
    changed = False
    for field, schema in properties.items():
        if field not in repaired or not isinstance(schema, dict):
            continue
        new_val, did_change = _coerce_value_to_schema(repaired[field], schema)
        if did_change:
            repaired[field] = new_val
            changed = True
    return repaired, changed


def _extract_mcp_jsonrpc_error_code(message: str) -> str | None:
    """Extract JSON-RPC style negative error code from freeform error text."""
    match = re.search(r'(-\d{4,5})', message or '')
    return match.group(1) if match else None


def _make_mcp_observation(action: MCPAction, payload: dict) -> MCPObservation:
    """Create an MCPObservation with aligned structured tool_result metadata."""
    obs = MCPObservation(
        content=_serialize_result_to_json(payload),
        name=action.name,
        arguments=action.arguments,
    )
    obs.tool_result = {
        'ok': bool(payload.get('ok', not payload.get('isError', False))),
        'retryable': bool(payload.get('retryable', False)),
        'error_code': payload.get('error_code'),
        'action': getattr(action, 'action', None),
        'observation': obs.observation,
    }
    return obs


async def _execute_wrapper_tool(
    action: MCPAction,
    mcps: list[MCPClient],
) -> MCPObservation:
    """Execute a wrapper tool and return observation."""
    try:

        async def _call_underlying(tool_name: str, args: dict):
            from types import SimpleNamespace

            inner_action = SimpleNamespace(name=tool_name, arguments=args)
            return await _call_mcp_raw(mcps, inner_action)

        wrapper_fn = WRAPPER_TOOL_REGISTRY[action.name]
        result_dict = await wrapper_fn(mcps, action.arguments, _call_underlying)
        return _make_mcp_observation(
            action, _normalize_mcp_success_payload(result_dict)
        )
    except Exception as e:
        logger.error('Wrapper tool %s failed: %s', action.name, e, exc_info=True)
        return _make_mcp_observation(
            action,
            _build_mcp_error_payload(
                action_name=action.name,
                message=str(e),
                code='WRAPPER_EXECUTION_FAILED',
                retryable=False,
            ),
        )


def _find_matching_mcp(mcps: list[MCPClient], action_name: str) -> MCPClient:
    """Find MCP client that supports the requested tool."""
    logger.debug('MCP clients: %s', mcps)
    logger.debug('MCP action name: %s', action_name)

    for client in mcps:
        logger.debug('MCP client tools: %s', client.tools)
        if _resolve_exposed_tool_name(client, action_name) is not None:
            logger.debug('Matching client: %s', client)
            return client

    msg = f'No matching MCP agent found for tool name: {action_name}'
    raise ValueError(msg)


def _resolve_exposed_tool_name(client: MCPClient, action_name: str) -> str | None:
    """Resolve either an exposed or protocol tool name to the exposed name."""
    tool_names = {tool.name for tool in getattr(client, 'tools', [])}
    if action_name in tool_names:
        return action_name

    exposed_to_protocol = getattr(client, 'exposed_to_protocol', {}) or {}
    for exposed_name, protocol_name in exposed_to_protocol.items():
        if protocol_name == action_name and exposed_name in tool_names:
            return exposed_name
    return None


async def _execute_direct_tool(
    action: MCPAction, matching_client: MCPClient
) -> MCPObservation:
    """Execute a direct MCP tool call and return observation."""
    from backend.engine.tools.prompt import get_terminal_tool_name as _terminal_tool

    try:
        if cached := get_cached(action.name, action.arguments):
            logger.debug('Cache hit for MCP tool %s', action.name)
            return _make_mcp_observation(action, _normalize_mcp_success_payload(cached))

        # Call tool
        response = await matching_client.call_tool(action.name, action.arguments)
        logger.debug('MCP response: %s', response)
        result_dict = model_dump_with_options(response, mode='json')

        # Cache result
        try:
            set_cache(action.name, action.arguments, result_dict)
        except Exception as cache_exc:
            logger.debug('Cache set skipped for %s: %s', action.name, cache_exc)

        # Serialize and return
        return _make_mcp_observation(
            action, _normalize_mcp_success_payload(result_dict)
        )
    except McpError as e:
        err_text = str(e)
        logger.error('MCP error when calling tool %s: %s', action.name, err_text)

        if _looks_like_mcp_validation_error(err_text):
            resolved_name = (
                _resolve_exposed_tool_name(matching_client, action.name) or action.name
            )
            tool_obj = getattr(matching_client, 'tool_map', {}).get(resolved_name)
            schema = (
                getattr(tool_obj, 'inputSchema', None) if tool_obj is not None else None
            )
            repaired_args, changed = _repair_args_with_schema(action.arguments, schema)

            if changed:
                logger.warning(
                    'MCP validation failed for %s; retrying once with schema-repaired args',
                    action.name,
                )
                try:
                    response = await matching_client.call_tool(
                        action.name, repaired_args
                    )
                    result_dict = model_dump_with_options(response, mode='json')
                    payload = _normalize_mcp_success_payload(result_dict)
                    payload['mcp_arg_repair_applied'] = True
                    payload['repaired_arguments'] = repaired_args
                    return _make_mcp_observation(action, payload)
                except Exception as retry_exc:
                    logger.error(
                        'MCP validation retry failed for %s: %s',
                        action.name,
                        retry_exc,
                    )

            code = _extract_mcp_jsonrpc_error_code(err_text) or '-32602'
            return _make_mcp_observation(
                action,
                _build_mcp_error_payload(
                    action_name=action.name,
                    message=(
                        f"MCP tool '{action.name}' rejected arguments with validation error ({code}).\n"
                        "Attempted schema-aware repair and single retry where possible.\n"
                        "Next step: call the same tool with arguments matching its input schema exactly."
                    ),
                    code='MCP_TOOL_VALIDATION_ERROR',
                    retryable=True,
                ),
            )

        return _make_mcp_observation(
            action,
            _build_mcp_error_payload(
                action_name=action.name,
                message=(
                    f"MCP tool '{action.name}' returned an error: {e}\n"
                    "You can try:\n"
                    "  1. Re-call the tool with corrected arguments\n"
                    f"  2. Use {_terminal_tool()} as a fallback to accomplish the same task"
                ),
                code='MCP_TOOL_ERROR',
                retryable=False,
            ),
        )
    except asyncio.TimeoutError as e:
        logger.error('MCP tool %s timed out: %s', action.name, e)
        return _make_mcp_observation(
            action,
            _build_mcp_error_payload(
                action_name=action.name,
                message=(
                    f"MCP tool '{action.name}' timed out (server did not respond in time).\n"
                    "The tool may be waiting on a slow network call or the MCP server may be stuck.\n"
                    "Try: a narrower query, or fall back to a non-MCP tool.\n"
                    "Tune limits: APP_MCP_CALL_TOTAL_BUDGET_SEC, APP_MCP_RECONNECT_SESSION_TIMEOUT_SEC."
                ),
                code='MCP_TOOL_TIMEOUT',
                retryable=True,
            ),
        )
    except Exception as e:
        # Catch-all for connection failures, timeouts, and unexpected errors
        logger.error(
            "MCP tool '%s' failed unexpectedly: %s", action.name, e, exc_info=True
        )
        return _make_mcp_observation(
            action,
            _build_mcp_error_payload(
                action_name=action.name,
                message=(
                    f"MCP server for tool '{action.name}' is unavailable (reason: "
                    f"{type(e).__name__}: {e}).\n"
                    "The MCP server may be disconnected or experiencing issues.\n"
                    "Fallback options:\n"
                    f"  1. Use {_terminal_tool()} to accomplish the same task\n"
                    "  2. Continue with non-MCP tools"
                ),
                code='MCP_SERVER_UNAVAILABLE',
                retryable=True,
            ),
        )


async def call_tool_mcp(
    mcps: list[MCPClient],
    action: MCPAction,
    *,
    configured_servers: list | None = None,  # noqa: ARG001 - kept for API compat
) -> Observation:
    """Call a tool on an MCP server and return the observation.

    Args:
        mcps: The list of MCP clients to execute the action on
        action: The MCP action to execute
        configured_servers: Unused; kept for backwards-compatible call sites.

    Returns:
        The observation from the MCP server

    """
    logger.debug('MCP action received: %s', action)

    # Handle wrapper tools
    if action.name in WRAPPER_TOOL_REGISTRY:
        return await _execute_wrapper_tool(action, mcps)

    from backend.engine.tools.prompt import get_terminal_tool_name as _terminal_tool

    if not mcps:
        return _make_mcp_observation(
            action,
            _build_mcp_error_payload(
                action_name=action.name,
                message=(
                    'No MCP clients are currently connected for this session. '
                    f'Use {_terminal_tool()} or another non-MCP tool instead; '
                    'only the tools listed in your active tool schema are available.'
                ),
                code='MCP_NO_CLIENTS',
                retryable=True,
            ),
        )

    # Handle direct tools with graceful fallback on client lookup failure
    try:
        matching_client = _find_matching_mcp(mcps, action.name)
    except ValueError:
        return _make_mcp_observation(
            action,
            _build_mcp_error_payload(
                action_name=action.name,
                message=(
                    f"MCP tool '{action.name}' is not available in this session.\n"
                    "Only the tool names listed in your active tool schema are valid — "
                    "pass them verbatim to `call_mcp_tool(tool_name=...)` with no "
                    "`server:` / `server/` / `server__` prefix.\n"
                    f"If none fit, use {_terminal_tool()} or another non-MCP tool."
                ),
                code='MCP_TOOL_UNAVAILABLE',
                retryable=False,
            ),
        )
    return await _execute_direct_tool(action, matching_client)


async def _call_mcp_raw(mcps: list[MCPClient], action) -> dict:
    matching_client: MCPClient | None = None
    resolved_exposed_name: str | None = None
    for client in mcps:
        resolved = _resolve_exposed_tool_name(client, action.name)
        if resolved is not None:
            matching_client = client
            resolved_exposed_name = resolved
            break
    if not matching_client or resolved_exposed_name is None:
        msg = f'Underlying tool {action.name} not found for wrapper'
        raise ValueError(msg)
    if cached := get_cached(action.name, action.arguments):
        return cached
    response = await matching_client.call_tool(resolved_exposed_name, action.arguments)
    result_dict = model_dump_with_options(response, mode='json')
    set_cache(action.name, action.arguments, result_dict)
    return result_dict


async def add_mcp_tools_to_agent(
    agent: Agent, runtime: Runtime, memory: Memory
) -> MCPConfig | None:
    """Add MCP tools to an agent."""
    assert (
        runtime.runtime_initialized
    ), 'Runtime must be initialized before adding MCP tools'
    extra_servers = []
    playbook_mcp_configs = memory.get_playbook_mcp_tools()
    for mcp_config in playbook_mcp_configs:
        # Convert playbook servers to unified format
        for server in mcp_config.servers:
            if server not in extra_servers:
                extra_servers.append(server)
                logger.warning(
                    'Added playbook MCP server: %s (%s)', server.name, server.type
                )

    updated_mcp_config = runtime.get_mcp_config(extra_servers)

    from backend.engine.tool_registry import _extract_tool_names

    reserved = frozenset(_extract_tool_names(agent.tools))
    if updated_mcp_config is not None:
        updated_mcp_config.mcp_exposed_name_reserved = reserved
    mcp_tools = await fetch_mcp_tools_from_config(
        updated_mcp_config,
        use_stdio=isinstance(runtime, LocalRuntimeInProcess),
        reserved_tool_names=reserved,
    )
    tool_names = [tool['function']['name'] for tool in mcp_tools]
    logger.info('Loaded %s MCP tools: %s', len(mcp_tools), tool_names)
    agent.set_mcp_tools(mcp_tools)
    agent.mcp_capability_status = get_mcp_bootstrap_status()
    return updated_mcp_config
