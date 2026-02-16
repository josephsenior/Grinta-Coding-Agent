"""OpenTelemetry instrumentation helpers for Forge."""

from __future__ import annotations

import contextlib
from typing import Any
from collections.abc import Generator


@contextlib.contextmanager
def redis_span(span_name: str) -> Generator[Any, None, None]:
    """Create an OTEL span for a Redis operation.

    Args:
        span_name: The name of the span to create.

    Yields:
        The created span object, or None if OTEL is not available.
    """
    try:
        from opentelemetry import trace as _otel_trace  # type: ignore
        from opentelemetry.trace import SpanKind as _SpanKind  # type: ignore
    except ImportError:
        yield None
        return

    tracer = _otel_trace.get_tracer("forge.redis")
    with tracer.start_as_current_span(span_name, kind=_SpanKind.CLIENT) as span:
        span.set_attribute("db.system", "redis")

        # Inject common trace context if available
        try:
            from backend.core.logger import get_trace_context

            ctx = get_trace_context()
            if ctx.get("trace_id"):
                span.set_attribute("forge.trace_id", str(ctx["trace_id"]))
        except ImportError:
            pass

        yield span
