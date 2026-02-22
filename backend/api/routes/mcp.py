"""Model Context Protocol (MCP) routes and helpers for Forge server tooling."""

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

from backend.core.logger import forge_logger as logger
from backend.core.logger import get_trace_context
from backend.core.provider_types import ProviderToken, ProviderType
from backend.api.user_auth import (
    get_access_token,
    get_provider_tokens,
    get_user_id,
)


# Lazy import to avoid circular dependency issues during config loading
def get_server_config():
    """Return server configuration module lazily to avoid circular import."""
    from backend.api.shared import server_config

    return server_config


def get_config():
    """Return Forge configuration without importing at module import time."""
    from backend.api.shared import config

    return config


mcp_server = FastMCP("mcp", stateless_http=True, mask_error_details=True)

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

        _mcp_tracer = _otel_trace.get_tracer("forge.mcp")
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
    conversation_id = headers.get("X-Forge-ServerConversation-ID", None)
    provider_tokens_raw = get_provider_tokens(request)
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
            span.set_attribute("forge.trace_id", str(trace_id))
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


async def _execute_with_tracing[ReturnT](
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
