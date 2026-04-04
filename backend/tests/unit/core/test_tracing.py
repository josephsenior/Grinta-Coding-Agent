"""Tests for backend.core.tracing – initialization, exporters, shutdown."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

import backend.core.tracing as tracing_mod


class _TracingTestBase(unittest.TestCase):
    """Reset module-level globals before each test."""

    def setUp(self):
        tracing_mod._state.initialized = False
        tracing_mod._state.tracer = None
        tracing_mod._state.trace_provider = None

    def tearDown(self):
        tracing_mod._state.initialized = False
        tracing_mod._state.tracer = None
        tracing_mod._state.trace_provider = None


# ---------------------------------------------------------------------------
# _should_initialize
# ---------------------------------------------------------------------------
class TestShouldInitialize(_TracingTestBase):
    def test_disabled(self):
        self.assertFalse(tracing_mod._should_initialize(enabled=False))

    def test_already_initialized(self):
        tracing_mod._state.initialized = True
        self.assertFalse(tracing_mod._should_initialize(enabled=True))

    def test_enabled_not_initialized(self):
        self.assertTrue(tracing_mod._should_initialize(enabled=True))


# ---------------------------------------------------------------------------
# _set_initialized / _finalize_tracer
# ---------------------------------------------------------------------------
class TestHelpers(_TracingTestBase):
    def test_set_initialized(self):
        self.assertFalse(tracing_mod._state.initialized)
        tracing_mod._set_initialized()
        self.assertTrue(tracing_mod._state.initialized)

    def test_finalize_tracer(self):
        mock_trace = MagicMock()
        mock_provider = MagicMock()
        mock_trace.get_tracer.return_value = 'tracer_obj'
        tracing_mod._finalize_tracer(mock_trace, mock_provider, 'svc', '1.0')
        self.assertIs(tracing_mod._state.trace_provider, mock_provider)
        self.assertEqual(tracing_mod._state.tracer, 'tracer_obj')
        mock_trace.get_tracer.assert_called_once_with('svc', '1.0')


# ---------------------------------------------------------------------------
# initialize_tracing
# ---------------------------------------------------------------------------
class TestInitializeTracing(_TracingTestBase):
    def test_disabled_does_nothing(self):
        tracing_mod.initialize_tracing(enabled=False)
        self.assertFalse(tracing_mod._state.initialized)

    def test_already_initialized_is_noop(self):
        tracing_mod._state.initialized = True
        tracing_mod.initialize_tracing(enabled=True)
        # Still just True, no error
        self.assertTrue(tracing_mod._state.initialized)

    @patch('backend.core.tracing._log_tracing_initialized')
    @patch('backend.core.tracing._set_initialized')
    @patch('backend.core.tracing._apply_span_processor')
    @patch('backend.core.tracing._finalize_tracer')
    @patch('backend.core.tracing._configure_exporter')
    @patch('backend.core.tracing._setup_tracer_provider')
    def test_happy_path(
        self, mock_setup, mock_exporter, mock_finalize, mock_apply, mock_set, mock_log
    ):
        mock_trace = MagicMock()
        mock_provider = MagicMock()
        mock_setup.return_value = (mock_trace, mock_provider)
        mock_exporter.return_value = (MagicMock(), 'console')

        tracing_mod.initialize_tracing(
            service_name='test',
            service_version='0.1',
            exporter='console',
            sample_rate=0.5,
            enabled=True,
        )

        mock_setup.assert_called_once_with('test', '0.1')
        mock_exporter.assert_called_once_with('console', None)
        mock_finalize.assert_called_once()
        mock_set.assert_called_once()
        mock_log.assert_called_once()

    @patch(
        'backend.core.tracing._setup_tracer_provider',
        side_effect=ImportError('no otel'),
    )
    def test_import_error_disables(self, mock_setup):
        tracing_mod.initialize_tracing(enabled=True)
        self.assertFalse(tracing_mod._state.initialized)

    @patch(
        'backend.core.tracing._setup_tracer_provider', side_effect=RuntimeError('bad')
    )
    def test_generic_error_disables(self, mock_setup):
        tracing_mod.initialize_tracing(enabled=True)
        self.assertFalse(tracing_mod._state.initialized)

    @patch('backend.core.tracing._log_tracing_initialized')
    @patch('backend.core.tracing._set_initialized')
    @patch('backend.core.tracing._finalize_tracer')
    @patch('backend.core.tracing._configure_exporter')
    @patch('backend.core.tracing._setup_tracer_provider')
    def test_none_exporter_skips_processor(
        self, mock_setup, mock_exporter, mock_finalize, mock_set, mock_log
    ):
        mock_setup.return_value = (MagicMock(), MagicMock())
        mock_exporter.return_value = (None, 'console')

        tracing_mod.initialize_tracing(enabled=True)
        # _apply_span_processor should NOT be called when exporter is None
        mock_finalize.assert_called_once()


# ---------------------------------------------------------------------------
# _configure_exporter routing
# ---------------------------------------------------------------------------
class TestConfigureExporter(_TracingTestBase):
    @patch('backend.core.tracing._configure_jaeger')
    def test_jaeger_route(self, mock_jaeger):
        mock_jaeger.return_value = MagicMock()
        result, etype = tracing_mod._configure_exporter('jaeger', None)
        self.assertEqual(etype, 'jaeger')
        mock_jaeger.assert_called_once()

    @patch('backend.core.tracing._configure_zipkin')
    def test_zipkin_route(self, mock_zipkin):
        mock_zipkin.return_value = MagicMock()
        result, etype = tracing_mod._configure_exporter('zipkin', None)
        self.assertEqual(etype, 'zipkin')

    @patch('backend.core.tracing._configure_otlp')
    def test_otlp_route(self, mock_otlp):
        mock_otlp.return_value = MagicMock()
        result, etype = tracing_mod._configure_exporter('otlp', None)
        self.assertEqual(etype, 'otlp')

    @patch('backend.core.tracing._configure_console')
    def test_unknown_defaults_to_console(self, mock_console):
        mock_console.return_value = MagicMock()
        result, etype = tracing_mod._configure_exporter('whatever', None)
        self.assertEqual(etype, 'console')


# ---------------------------------------------------------------------------
# get_tracer
# ---------------------------------------------------------------------------
class TestGetTracer(_TracingTestBase):
    def test_returns_existing_tracer(self):
        tracing_mod._state.initialized = True
        tracing_mod._state.tracer = 'my_tracer'
        self.assertEqual(tracing_mod.get_tracer(), 'my_tracer')

    @patch('backend.core.tracing.initialize_tracing')
    def test_auto_initializes_when_not_initialized(self, mock_init):
        tracing_mod._state.initialized = False
        tracing_mod._state.tracer = 'auto_tracer'
        result = tracing_mod.get_tracer()
        mock_init.assert_called_once()
        self.assertEqual(result, 'auto_tracer')


# ---------------------------------------------------------------------------
# shutdown_tracing
# ---------------------------------------------------------------------------
class TestShutdownTracing(_TracingTestBase):
    def test_shutdown_with_provider(self):
        mock_provider = MagicMock()
        tracing_mod._state.trace_provider = mock_provider
        tracing_mod._state.initialized = True

        tracing_mod.shutdown_tracing()

        mock_provider.shutdown.assert_called_once()
        self.assertIsNone(tracing_mod._state.trace_provider)
        self.assertFalse(tracing_mod._state.initialized)

    def test_shutdown_no_provider(self):
        tracing_mod._state.trace_provider = None
        tracing_mod.shutdown_tracing()
        self.assertFalse(tracing_mod._state.initialized)

    def test_shutdown_error_still_cleans_up(self):
        mock_provider = MagicMock()
        mock_provider.shutdown.side_effect = RuntimeError('shutdown error')
        tracing_mod._state.trace_provider = mock_provider
        tracing_mod._state.initialized = True

        tracing_mod.shutdown_tracing()

        self.assertIsNone(tracing_mod._state.trace_provider)
        self.assertFalse(tracing_mod._state.initialized)


# ---------------------------------------------------------------------------
# _log_tracing_initialized
# ---------------------------------------------------------------------------
class TestLogTracingInitialized(_TracingTestBase):
    @patch('backend.core.tracing.logger')
    def test_logs_info(self, mock_logger):
        tracing_mod._log_tracing_initialized('svc', '1.0', 'console', 0.1)
        mock_logger.info.assert_called_once()
        args = mock_logger.info.call_args
        self.assertIn('svc', str(args))


if __name__ == '__main__':
    unittest.main()
