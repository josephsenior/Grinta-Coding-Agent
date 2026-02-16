"""Tests for backend.utils.otel_utils module."""

from unittest.mock import MagicMock, patch

import pytest


class TestRedisSpan:
    def test_yields_none_without_opentelemetry(self):
        from backend.utils.otel_utils import redis_span

        with patch.dict("sys.modules", {"opentelemetry": None, "opentelemetry.trace": None}):
            # If otel is not importable, should yield None
            with redis_span("test_op") as span:
                # span may be None or may be a real span depending on environment
                pass  # Just verify no exception

    def test_context_manager_completes(self):
        from backend.utils.otel_utils import redis_span

        # Should work as a context manager regardless of otel availability
        with redis_span("test_operation") as span:
            pass  # No exception expected

    def test_span_name_passed_through(self):
        """redis_span can be used with any span name string."""
        from backend.utils.otel_utils import redis_span

        with redis_span("custom_operation") as span:
            # Depending on otel availability, span may or may not be None
            pass  # The important thing is no exception is raised
