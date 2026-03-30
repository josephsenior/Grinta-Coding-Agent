"""Distributed tracing module with OpenTelemetry defaults and exporters."""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

class _TracingState:
    """Internal state container for initialized tracing components."""

    initialized: bool = False
    tracer: Any = None
    trace_provider: Any = None


_state = _TracingState()


def initialize_tracing(

    service_name: str = "app",
    service_version: str = "1.0.0",
    exporter: str = "console",
    endpoint: str | None = None,
    sample_rate: float = 0.1,
    enabled: bool = True,
) -> None:
    """Initialize OpenTelemetry tracing with defaults.

    Args:
        service_name: Service name for tracing
        service_version: Service version for tracing
        exporter: Tracing exporter ('jaeger', 'zipkin', 'otlp', 'console')
        endpoint: Tracing endpoint URL
        sample_rate: Trace sampling rate (0.0 to 1.0)
        enabled: Whether tracing is enabled

    """
    global _tracing_initialized, _tracer, _trace_provider

    if not _should_initialize(enabled):
        return

    try:
        trace, tracer_provider = _setup_tracer_provider(service_name, service_version)
        span_exporter, exporter_type = _configure_exporter(exporter, endpoint)
        if span_exporter:
            _apply_span_processor(tracer_provider, span_exporter, sample_rate)
        _finalize_tracer(trace, tracer_provider, service_name, service_version)
        _set_initialized()
        _log_tracing_initialized(
            service_name, service_version, exporter_type, sample_rate
        )
    except ImportError as exc:
        logger.warning("OpenTelemetry not available: %s. Tracing disabled.", exc)
    except Exception as exc:
        logger.error("Failed to initialize tracing: %s", exc, exc_info=True)


def _should_initialize(enabled: bool) -> bool:
    if not enabled:
        logger.debug("Tracing disabled")
        return False
    if _state.initialized:
        logger.debug("Tracing already initialized")
        return False
    return True


def _setup_tracer_provider(service_name: str, service_version: str):
    from opentelemetry import trace
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider

    resource = Resource.create(
        {
            "service.name": service_name,
            "service.version": service_version,
            "service.instance.id": os.getenv("HOSTNAME", "app"),
        }
    )
    tracer_provider = TracerProvider(resource=resource)
    trace.set_tracer_provider(tracer_provider)
    return trace, tracer_provider


def _configure_exporter(exporter: str, endpoint: str | None) -> tuple[Any | None, str]:
    exporter_type = exporter
    if exporter == "jaeger":
        exporter_instance = _configure_jaeger(endpoint)
    elif exporter == "zipkin":
        exporter_instance = _configure_zipkin(endpoint)
    elif exporter == "otlp":
        exporter_instance = _configure_otlp(endpoint)
    else:
        exporter_instance = _configure_console()
        exporter_type = "console"
    return exporter_instance, exporter_type


def _try_jaeger_otlp(endpoint: str | None) -> Any | None:
    """Try OTLP exporter for Jaeger. Returns exporter or None on ImportError."""
    try:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
            OTLPSpanExporter,
        )
    except ImportError:
        logger.warning("OTLP exporter not available, falling back to Thrift")
        return None
    otlp = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT") or endpoint or "http://localhost:4318/v1/traces"
    if not otlp.endswith("/v1/traces"):
        otlp = otlp.rstrip("/") + "/v1/traces"
    logger.info("Jaeger OTLP exporter configured: %s", otlp)
    return OTLPSpanExporter(endpoint=otlp)


def _try_jaeger_thrift(endpoint: str | None) -> Any | None:
    """Try Jaeger Thrift exporter. Returns exporter or None on ImportError."""
    try:
        from opentelemetry.exporter.jaeger.thrift import JaegerExporter
    except ImportError:
        logger.warning("Jaeger Thrift exporter not available, falling back to console")
        return None
    ep = endpoint or os.getenv("JAEGER_ENDPOINT", "http://localhost:14268/api/traces")
    exporter = JaegerExporter(
        agent_host_name=os.getenv("JAEGER_AGENT_HOST", "localhost"),
        agent_port=int(os.getenv("JAEGER_AGENT_PORT", "6831")),
        endpoint=ep,
    )
    logger.info("Jaeger Thrift exporter configured: %s", ep)
    return exporter


def _configure_jaeger(endpoint: str | None):
    """Configure Jaeger exporter with support for both OTLP and Thrift protocols."""
    try:
        otlp_env = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
        use_otlp = otlp_env is not None or (
            endpoint and ("4318" in endpoint or "/v1/traces" in endpoint)
        )
        if use_otlp:
            exporter = _try_jaeger_otlp(otlp_env or endpoint)
            if exporter is not None:
                return exporter
        exporter = _try_jaeger_thrift(endpoint)
        return exporter if exporter is not None else _configure_console()
    except Exception as e:
        logger.error("Failed to configure Jaeger exporter: %s", e, exc_info=True)
        return _configure_console()


def _configure_zipkin(endpoint: str | None):
    try:
        from opentelemetry.exporter.zipkin.json import ZipkinExporter

        endpoint = endpoint or os.getenv(
            "ZIPKIN_ENDPOINT", "http://localhost:9411/api/v2/spans"
        )
        exporter = ZipkinExporter(endpoint=endpoint)
        logger.info("Zipkin exporter configured: %s", endpoint)
        return exporter
    except ImportError:
        logger.warning("Zipkin exporter not available, falling back to console")
        return _configure_console()


def _configure_otlp(endpoint: str | None):
    try:
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
            OTLPSpanExporter,
        )

        endpoint = endpoint or os.getenv(
            "OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317"
        )
        exporter = OTLPSpanExporter(endpoint=endpoint)
        logger.info("OTLP exporter configured: %s", endpoint)
        return exporter
    except ImportError:
        logger.warning("OTLP exporter not available, falling back to console")
        return _configure_console()


def _configure_console():
    from opentelemetry.sdk.trace.export import ConsoleSpanExporter

    logger.info("Console exporter configured")
    return ConsoleSpanExporter()


def _apply_span_processor(
    tracer_provider, span_exporter: Any, sample_rate: float
) -> None:
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    from opentelemetry.sdk.trace.sampling import TraceIdRatioBased

    sampler = TraceIdRatioBased(sample_rate)
    tracer_provider.sampler = sampler
    tracer_provider.add_span_processor(BatchSpanProcessor(span_exporter))


def _finalize_tracer(trace_module, tracer_provider, service_name, service_version):
    _state.trace_provider = tracer_provider
    _state.tracer = trace_module.get_tracer(service_name, service_version)


def _set_initialized():
    _state.initialized = True


def _log_tracing_initialized(
    service_name: str, service_version: str, exporter: str, sample_rate: float
) -> None:
    logger.info(
        "Tracing initialized: service=%s, version=%s, exporter=%s, sample_rate=%s",
        service_name,
        service_version,
        exporter,
        sample_rate,
    )


def get_tracer(name: str | None = None) -> Any:
    """Get tracer instance.

    Args:
        name: Tracer name (defaults to service name)

    Returns:
        Tracer instance or None if tracing not initialized

    """
    if not _state.initialized:
        # Auto-initialize with defaults
        initialize_tracing(
            service_name=os.getenv("TRACING_SERVICE_NAME", "app"),
            service_version=os.getenv("TRACING_SERVICE_VERSION", "1.0.0"),
            exporter=os.getenv("TRACING_EXPORTER", "console"),
            endpoint=os.getenv("TRACING_ENDPOINT"),
            sample_rate=float(os.getenv("TRACING_SAMPLE_RATE", "0.1")),
            enabled=os.getenv("TRACING_ENABLED", "true").lower() == "true",
        )

    if _state.tracer is None:
        try:
            from opentelemetry import trace

            service_name = os.getenv("TRACING_SERVICE_NAME", "app")
            _state.tracer = trace.get_tracer(name or service_name)
        except ImportError:
            logger.warning("OpenTelemetry not available")
            return None

    return _state.tracer


def shutdown_tracing() -> None:
    """Shutdown tracing provider."""
    if _state.trace_provider:
        try:
            _state.trace_provider.shutdown()
            logger.info("Tracing shutdown")
        except Exception as e:
            logger.error("Error shutting down tracing: %s", e, exc_info=True)
        finally:
            _state.trace_provider = None
            _state.initialized = False


# Auto-initialize tracing on module import if enabled
if os.getenv("TRACING_ENABLED", "true").lower() == "true":
    initialize_tracing(
        service_name=os.getenv("TRACING_SERVICE_NAME", "app"),
        service_version=os.getenv("TRACING_SERVICE_VERSION", "1.0.0"),
        exporter=os.getenv("TRACING_EXPORTER", "console"),
        endpoint=os.getenv("TRACING_ENDPOINT"),
        sample_rate=float(os.getenv("TRACING_SAMPLE_RATE", "0.1")),
        enabled=True,
    )
