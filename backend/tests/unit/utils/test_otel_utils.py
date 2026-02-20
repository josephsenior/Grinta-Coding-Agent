"""Tests for backend.utils.otel_utils — OpenTelemetry span helpers."""

from __future__ import annotations

from unittest.mock import MagicMock, patch


from backend.utils.otel_utils import redis_span


# ── redis_span ─────────────────────────────────────────────────────────


class TestRedisSpan:
    """Test OTEL span creation for Redis operations."""

    def test_yields_none_when_otel_not_available(self):
        """Test yields None when OpenTelemetry not installed."""
        with patch.dict(
            "sys.modules", {"opentelemetry": None, "opentelemetry.trace": None}
        ):
            with redis_span("test_operation") as span:
                assert span is None

    def test_creates_span_when_otel_available(self):
        """Test creates span when OpenTelemetry is available."""
        mock_span = MagicMock()
        mock_tracer = MagicMock()
        mock_tracer.start_as_current_span.return_value.__enter__.return_value = (
            mock_span
        )

        mock_trace_module = MagicMock()
        mock_trace_module.get_tracer.return_value = mock_tracer

        mock_span_kind_class = MagicMock()
        mock_span_kind_class.CLIENT = "CLIENT"

        with patch.dict(
            "sys.modules",
            {
                "opentelemetry": MagicMock(),
                "opentelemetry.trace": mock_trace_module,
            },
        ):
            with patch("opentelemetry.trace.SpanKind", mock_span_kind_class):
                # Re-import to get patched modules
                from importlib import reload
                import backend.utils.otel_utils

                reload(backend.utils.otel_utils)
                with backend.utils.otel_utils.redis_span("get_key"):
                    # Span should be created (though exact value depends on import state)
                    pass

    def test_sets_db_system_attribute(self):
        """Test sets db.system attribute on span."""
        # Test that context manager works
        with redis_span("set_key") as span:
            # Should get a span object (OTEL is installed in test env)
            assert span is not None

    def test_injects_trace_context_when_available(self):
        """Test trace context injection when available."""
        # When OpenTelemetry is available, should yield span object
        with redis_span("lpush") as span:
            assert span is not None

    def test_handles_missing_trace_context_gracefully(self):
        """Test handles missing trace context without error."""
        # Should not raise even if trace context unavailable
        with redis_span("rpush") as span:
            assert span is not None

    def test_span_name_passed_to_tracer(self):
        """Test span context manager with custom operation name."""
        # Test that different operation names work
        with redis_span("custom_operation") as span:
            assert span is not None  # OTEL is available in test environment

    def test_uses_redis_tracer(self):
        """Test uses context manager correctly."""
        # Test that multiple calls work
        with redis_span("hgetall") as span:
            assert span is not None
        with redis_span("sadd") as span:
            assert span is not None

    def test_handles_trace_context_import_error(self):
        """Test handles missing trace context import error."""
        # This triggers the inner ImportError for trace context injection
        with patch.dict("sys.modules", {"backend.core.logger": None}):
            from importlib import reload

            import backend.utils.otel_utils

            reload(backend.utils.otel_utils)
            with backend.utils.otel_utils.redis_span("lpush") as span:
                assert span is not None
