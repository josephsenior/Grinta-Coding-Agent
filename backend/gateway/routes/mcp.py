"""Model Context Protocol (MCP) routes and helpers for App server tooling."""

# Note: NOT using "from __future__ import annotations" to avoid Field resolution issues in fastmcp
# from __future__ import annotations

import contextlib
import os
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, TypeVar

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.dependencies import get_http_request

# Import SecretStr from pydantic
from pydantic import SecretStr

from backend.core.logger import app_logger as logger
from backend.core.logger import get_trace_context
from backend.core.provider_types import ProviderToken, ProviderType
from backend.gateway.user_auth import (
    get_access_token,
    get_provider_tokens,
    get_user_id,
)


# Lazy import to avoid circular dependency issues during config loading
def get_server_config():
    """Return server configuration module lazily to avoid circular import."""
    from backend.gateway.app_accessors import server_config

    return server_config


def get_config():
    """Return application configuration without importing at module import time."""
    from backend.gateway.app_accessors import get_config as _get_config

    return _get_config()


mcp_server = FastMCP("mcp", mask_error_details=True)

# Optional OpenTelemetry setup for MCP instrumentation
_OTEL_MCP_ENABLED = os.getenv(
    "OTEL_INSTRUMENT_MCP", os.getenv("OTEL_ENABLED", "false")
).lower() in (
    "true",
    "1",
    "yes",
)
_mcp_tracer: Any | None = None
_SPAN_KIND: Any | None = None
try:
    if _OTEL_MCP_ENABLED:
        from opentelemetry import trace as _otel_trace  # type: ignore
        from opentelemetry.trace import SpanKind  # type: ignore

        _mcp_tracer = _otel_trace.get_tracer("app.mcp")
        _SPAN_KIND = SpanKind
except Exception:  # pragma: no cover - optional dependency
    _mcp_tracer = None
    _SPAN_KIND = None

ReturnT = TypeVar("ReturnT")


@dataclass
class _McpRequestContext:
    conversation_id: str | None
    provider_tokens: dict[ProviderType, ProviderToken] | None
    access_token: SecretStr | None
    user_id: str | None


async def _request_context() -> _McpRequestContext:
    request = get_http_request()
    headers = request.headers
    conversation_id = headers.get("X-App-ServerConversation-ID", None)
    provider_tokens_raw = get_provider_tokens()
    provider_tokens = (
        dict(provider_tokens_raw) if provider_tokens_raw is not None else None
    )
    access_token_raw: str | None = get_access_token(request)
    access_token = SecretStr(access_token_raw) if access_token_raw else None
    user_id = get_user_id(request)
    return _McpRequestContext(
        conversation_id=conversation_id,
        provider_tokens=provider_tokens,
        access_token=access_token,
        user_id=user_id,
    )


def _provider_token(
    context: _McpRequestContext, provider: ProviderType
) -> ProviderToken:
    if not context.provider_tokens:
        return ProviderToken()
    return context.provider_tokens.get(provider, ProviderToken())


def _otel_sample_rate() -> float:
    try:
        return float(
            os.getenv("OTEL_SAMPLE_MCP", os.getenv("OTEL_SAMPLE_DEFAULT", "1.0"))
        )
    except Exception:
        return 1.0


def _span_context_manager():
    if _mcp_tracer is None:
        return contextlib.nullcontext()
    sample_rate = max(0.0, min(1.0, _otel_sample_rate()))
    if random.random() >= sample_rate:
        return contextlib.nullcontext()
    span_kind = _SPAN_KIND
    if span_kind is None:
        return contextlib.nullcontext()
    return _mcp_tracer.start_as_current_span("mcp.request", kind=span_kind.CLIENT)


def _set_span_attributes(
    span,
    tool_name: str,
    resource: str,
    conversation_id: str | None,
) -> None:
    try:
        span.set_attribute("tool.name", tool_name)
        span.set_attribute("tool.kind", "mcp")
        span.set_attribute("mcp.server.name", "mcp")
        span.set_attribute("mcp.method", tool_name)
        span.set_attribute("mcp.resource", resource)
        if conversation_id:
            span.set_attribute("conversation.id", conversation_id)
        ctx = get_trace_context()
        trace_id = ctx.get("trace_id")
        if trace_id:
            span.set_attribute("app.trace_id", str(trace_id))
    except Exception as e:
        logger.debug("Failed to set trace attributes: %s", e)


@contextlib.contextmanager
def _mcp_span(tool_name: str, resource: str, conversation_id: str | None):
    span_ref = None
    with _span_context_manager() as span:
        span_ref = span
        if span_ref is not None:
            _set_span_attributes(span_ref, tool_name, resource, conversation_id)
        try:
            yield span_ref
        except Exception as exc:
            if span_ref is not None:
                try:
                    span_ref.record_exception(exc)
                    span_ref.set_attribute("error", True)
                except Exception:
                    pass
            raise


async def _execute_with_tracing(
    tool_name: str,
    resource: str,
    conversation_id: str | None,
    action: Callable[[], Awaitable[ReturnT]],
    error_prefix: str,
) -> ReturnT:
    try:
        with _mcp_span(tool_name, resource, conversation_id):
            return await action()
    except Exception as exc:
        error = f"{error_prefix}: {exc}"
        logger.error(error)
        raise ToolError(error) from exc


def _registered_tools() -> dict[str, Any]:
    tool_manager = getattr(mcp_server, "_tool_manager", None)
    tools = getattr(tool_manager, "_tools", None)
    if isinstance(tools, dict):
        return tools
    return {}


def get_registered_tool_names() -> list[str]:
    """Return the local app-mcp tool names currently registered on FastMCP."""
    return sorted(str(name) for name in _registered_tools())


def get_registered_tool_count() -> int:
    """Return the local app-mcp tool count for config-layer gating."""
    return len(_registered_tools())


def _build_server_ready_status() -> dict[str, Any]:
    from backend.gateway.routes.health import get_ready_status_snapshot

    return get_ready_status_snapshot()


def _build_workspace_info() -> dict[str, Any]:
    from backend.core.workspace_resolution import get_effective_workspace_root

    config = get_config()
    workspace_root = get_effective_workspace_root()
    return {
        "path": str(workspace_root) if workspace_root is not None else None,
        "project_root": str(getattr(config, "project_root", None) or ""),
        "local_data_root": str(getattr(config, "local_data_root", "") or ""),
    }


def _build_public_server_config() -> dict[str, Any]:
    return get_server_config().get_config()


def _build_configured_mcp_servers() -> list[dict[str, Any]]:
    config = get_config()
    return [
        {
            "name": server.name,
            "type": server.type,
            "transport": server.transport,
            "url": server.url,
            "command": server.command,
            "args": list(server.args),
            "usage_hint": server.usage_hint,
        }
        for server in config.mcp.servers
    ]


def _list_available_models() -> list[str]:
    from backend.gateway.app_state import get_app_state
    from backend.inference.model_catalog import get_supported_llm_models

    return get_supported_llm_models(get_app_state().config)


def _list_available_agents() -> list[str]:
    from importlib import import_module

    import_module("backend.engine")
    from backend.orchestration.agent import Agent

    return sorted(Agent.list_agents())


def _list_security_analyzers() -> list[str]:
    from backend.security.options import SecurityAnalyzers

    return sorted(SecurityAnalyzers.keys())


@mcp_server.tool(description="Return the gateway readiness snapshot and dependency checks.")
async def get_server_ready_status() -> dict[str, Any]:
    context = await _request_context()

    async def action() -> dict[str, Any]:
        return _build_server_ready_status()

    return await _execute_with_tracing(
        "get_server_ready_status",
        "server.health.ready",
        context.conversation_id,
        action,
        "Failed to load server readiness status",
    )


@mcp_server.tool(description="Return system metrics and runtime server information.")
async def get_server_info() -> dict[str, Any]:
    context = await _request_context()

    async def action() -> dict[str, Any]:
        from backend.gateway.routes.health import get_system_info

        return get_system_info()

    return await _execute_with_tracing(
        "get_server_info",
        "server.info",
        context.conversation_id,
        action,
        "Failed to load server info",
    )


@mcp_server.tool(description="Return the active workspace and local storage roots.")
async def get_workspace_info() -> dict[str, Any]:
    context = await _request_context()

    async def action() -> dict[str, Any]:
        return _build_workspace_info()

    return await _execute_with_tracing(
        "get_workspace_info",
        "workspace.info",
        context.conversation_id,
        action,
        "Failed to load workspace info",
    )


@mcp_server.tool(description="List the LLM models currently exposed by the gateway.")
async def list_available_models() -> list[str]:
    context = await _request_context()

    async def action() -> list[str]:
        return _list_available_models()

    return await _execute_with_tracing(
        "list_available_models",
        "options.models",
        context.conversation_id,
        action,
        "Failed to load available models",
    )


@mcp_server.tool(description="List the registered agent implementations available on the gateway.")
async def list_available_agents() -> list[str]:
    context = await _request_context()

    async def action() -> list[str]:
        return _list_available_agents()

    return await _execute_with_tracing(
        "list_available_agents",
        "options.agents",
        context.conversation_id,
        action,
        "Failed to load available agents",
    )


@mcp_server.tool(description="List the configured security analyzers exposed by the gateway.")
async def list_security_analyzers() -> list[str]:
    context = await _request_context()

    async def action() -> list[str]:
        return _list_security_analyzers()

    return await _execute_with_tracing(
        "list_security_analyzers",
        "options.security_analyzers",
        context.conversation_id,
        action,
        "Failed to load security analyzers",
    )


@mcp_server.tool(description="Return the public server configuration snapshot used by the gateway.")
async def get_public_server_config() -> dict[str, Any]:
    context = await _request_context()

    async def action() -> dict[str, Any]:
        return _build_public_server_config()

    return await _execute_with_tracing(
        "get_public_server_config",
        "options.config",
        context.conversation_id,
        action,
        "Failed to load public server config",
    )


@mcp_server.tool(description="List the MCP servers currently configured on the gateway.")
async def list_configured_mcp_servers() -> list[dict[str, Any]]:
    context = await _request_context()

    async def action() -> list[dict[str, Any]]:
        return _build_configured_mcp_servers()

    return await _execute_with_tracing(
        "list_configured_mcp_servers",
        "mcp.servers",
        context.conversation_id,
        action,
        "Failed to load configured MCP servers",
    )
