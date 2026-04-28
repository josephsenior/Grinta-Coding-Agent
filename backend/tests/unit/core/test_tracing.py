"""Tests for backend.core.tracing – initialization, exporters, shutdown."""

from __future__ import annotations

import builtins
import os
import sys
import unittest
from types import ModuleType
from unittest.mock import MagicMock, patch

import backend.core.tracing as tracing_mod


def _package(name: str) -> ModuleType:
    module = ModuleType(name)
    module.__path__ = []
    return module


def _import_with_missing(*names: str):
    original_import = builtins.__import__
    missing = set(names)

    def _fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name in missing:
            raise ImportError(f'missing {name}')
        return original_import(name, globals, locals, fromlist, level)

    return _fake_import


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


class TestExporterHelpers(_TracingTestBase):
    @patch('backend.core.tracing.logger')
    def test_try_jaeger_otlp_returns_none_on_import_error(self, mock_logger):
        with patch('builtins.__import__', side_effect=_import_with_missing(
            'opentelemetry.exporter.otlp.proto.http.trace_exporter'
        )):
            self.assertIsNone(tracing_mod._try_jaeger_otlp(None))

        mock_logger.warning.assert_called_once()

    @patch.dict(os.environ, {}, clear=False)
    def test_try_jaeger_otlp_normalizes_endpoint_suffix(self):
        exporter_module = ModuleType(
            'opentelemetry.exporter.otlp.proto.http.trace_exporter'
        )
        exporter_ctor = MagicMock(return_value='otlp_exporter')
        exporter_module.OTLPSpanExporter = exporter_ctor

        with patch.dict(
            sys.modules,
            {
                'opentelemetry': _package('opentelemetry'),
                'opentelemetry.exporter': _package('opentelemetry.exporter'),
                'opentelemetry.exporter.otlp': _package(
                    'opentelemetry.exporter.otlp'
                ),
                'opentelemetry.exporter.otlp.proto': _package(
                    'opentelemetry.exporter.otlp.proto'
                ),
                'opentelemetry.exporter.otlp.proto.http': _package(
                    'opentelemetry.exporter.otlp.proto.http'
                ),
                'opentelemetry.exporter.otlp.proto.http.trace_exporter': (
                    exporter_module
                ),
            },
            clear=False,
        ):
            result = tracing_mod._try_jaeger_otlp('http://collector:4318')

        self.assertEqual(result, 'otlp_exporter')
        exporter_ctor.assert_called_once_with(
            endpoint='http://collector:4318/v1/traces'
        )

    @patch('backend.core.tracing.logger')
    def test_try_jaeger_thrift_returns_none_on_import_error(self, mock_logger):
        with patch('builtins.__import__', side_effect=_import_with_missing(
            'opentelemetry.exporter.jaeger.thrift'
        )):
            self.assertIsNone(tracing_mod._try_jaeger_thrift(None))

        mock_logger.warning.assert_called_once()

    @patch.dict(
        os.environ,
        {'JAEGER_AGENT_HOST': 'jaeger-host', 'JAEGER_AGENT_PORT': '7000'},
        clear=False,
    )
    def test_try_jaeger_thrift_uses_endpoint_and_agent_settings(self):
        thrift_module = ModuleType('opentelemetry.exporter.jaeger.thrift')
        exporter_ctor = MagicMock(return_value='jaeger_exporter')
        thrift_module.JaegerExporter = exporter_ctor

        with patch.dict(
            sys.modules,
            {
                'opentelemetry': _package('opentelemetry'),
                'opentelemetry.exporter': _package('opentelemetry.exporter'),
                'opentelemetry.exporter.jaeger': _package(
                    'opentelemetry.exporter.jaeger'
                ),
                'opentelemetry.exporter.jaeger.thrift': thrift_module,
            },
            clear=False,
        ):
            result = tracing_mod._try_jaeger_thrift('http://jaeger/api/traces')

        self.assertEqual(result, 'jaeger_exporter')
        exporter_ctor.assert_called_once_with(
            agent_host_name='jaeger-host',
            agent_port=7000,
            endpoint='http://jaeger/api/traces',
        )

    @patch('backend.core.tracing._try_jaeger_otlp', return_value='otlp_exporter')
    @patch('backend.core.tracing._try_jaeger_thrift')
    def test_configure_jaeger_prefers_otlp_when_endpoint_requests_it(
        self, mock_thrift, mock_otlp
    ):
        result = tracing_mod._configure_jaeger('http://collector:4318')

        self.assertEqual(result, 'otlp_exporter')
        mock_otlp.assert_called_once_with('http://collector:4318')
        mock_thrift.assert_not_called()

    @patch('backend.core.tracing._configure_console', return_value='console_exporter')
    @patch('backend.core.tracing._try_jaeger_thrift', return_value=None)
    @patch('backend.core.tracing._try_jaeger_otlp', return_value=None)
    def test_configure_jaeger_falls_back_to_console_when_exporters_missing(
        self, mock_otlp, mock_thrift, mock_console
    ):
        with patch.dict(
            os.environ,
            {'OTEL_EXPORTER_OTLP_ENDPOINT': 'http://collector:4318'},
            clear=False,
        ):
            result = tracing_mod._configure_jaeger(None)

        self.assertEqual(result, 'console_exporter')
        mock_otlp.assert_called_once_with('http://collector:4318')
        mock_thrift.assert_called_once_with(None)
        mock_console.assert_called_once()

    @patch('backend.core.tracing._configure_console', return_value='console_exporter')
    @patch('backend.core.tracing._try_jaeger_otlp', side_effect=RuntimeError('boom'))
    def test_configure_jaeger_handles_unexpected_errors(
        self, mock_otlp, mock_console
    ):
        result = tracing_mod._configure_jaeger('http://collector:4318')

        self.assertEqual(result, 'console_exporter')
        mock_otlp.assert_called_once_with('http://collector:4318')
        mock_console.assert_called_once()

    def test_configure_zipkin_uses_endpoint(self):
        zipkin_module = ModuleType('opentelemetry.exporter.zipkin.json')
        exporter_ctor = MagicMock(return_value='zipkin_exporter')
        zipkin_module.ZipkinExporter = exporter_ctor

        with patch.dict(
            sys.modules,
            {
                'opentelemetry': _package('opentelemetry'),
                'opentelemetry.exporter': _package('opentelemetry.exporter'),
                'opentelemetry.exporter.zipkin': _package(
                    'opentelemetry.exporter.zipkin'
                ),
                'opentelemetry.exporter.zipkin.json': zipkin_module,
            },
            clear=False,
        ):
            result = tracing_mod._configure_zipkin('http://zipkin/api/v2/spans')

        self.assertEqual(result, 'zipkin_exporter')
        exporter_ctor.assert_called_once_with(endpoint='http://zipkin/api/v2/spans')

    @patch('backend.core.tracing._configure_console', return_value='console_exporter')
    def test_configure_zipkin_falls_back_to_console_on_import_error(
        self, mock_console
    ):
        with patch('builtins.__import__', side_effect=_import_with_missing(
            'opentelemetry.exporter.zipkin.json'
        )):
            result = tracing_mod._configure_zipkin(None)

        self.assertEqual(result, 'console_exporter')
        mock_console.assert_called_once()

    def test_configure_otlp_uses_endpoint(self):
        otlp_module = ModuleType('opentelemetry.exporter.otlp.proto.grpc.trace_exporter')
        exporter_ctor = MagicMock(return_value='grpc_exporter')
        otlp_module.OTLPSpanExporter = exporter_ctor

        with patch.dict(
            sys.modules,
            {
                'opentelemetry': _package('opentelemetry'),
                'opentelemetry.exporter': _package('opentelemetry.exporter'),
                'opentelemetry.exporter.otlp': _package(
                    'opentelemetry.exporter.otlp'
                ),
                'opentelemetry.exporter.otlp.proto': _package(
                    'opentelemetry.exporter.otlp.proto'
                ),
                'opentelemetry.exporter.otlp.proto.grpc': _package(
                    'opentelemetry.exporter.otlp.proto.grpc'
                ),
                'opentelemetry.exporter.otlp.proto.grpc.trace_exporter': (
                    otlp_module
                ),
            },
            clear=False,
        ):
            result = tracing_mod._configure_otlp('http://collector:4317')

        self.assertEqual(result, 'grpc_exporter')
        exporter_ctor.assert_called_once_with(endpoint='http://collector:4317')

    @patch('backend.core.tracing._configure_console', return_value='console_exporter')
    def test_configure_otlp_falls_back_to_console_on_import_error(
        self, mock_console
    ):
        with patch('builtins.__import__', side_effect=_import_with_missing(
            'opentelemetry.exporter.otlp.proto.grpc.trace_exporter'
        )):
            result = tracing_mod._configure_otlp(None)

        self.assertEqual(result, 'console_exporter')
        mock_console.assert_called_once()


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

    def test_get_tracer_imports_trace_module_when_state_is_empty(self):
        trace_module = ModuleType('opentelemetry.trace')
        trace_module.get_tracer = MagicMock(return_value='imported_tracer')
        otel_module = _package('opentelemetry')
        otel_module.trace = trace_module

        tracing_mod._state.initialized = True
        tracing_mod._state.tracer = None

        with patch.dict(
            sys.modules,
            {
                'opentelemetry': otel_module,
                'opentelemetry.trace': trace_module,
            },
            clear=False,
        ):
            result = tracing_mod.get_tracer('custom-name')

        self.assertEqual(result, 'imported_tracer')
        trace_module.get_tracer.assert_called_once_with('custom-name')

    @patch('backend.core.tracing.logger')
    def test_get_tracer_returns_none_on_import_error(self, mock_logger):
        tracing_mod._state.initialized = True
        tracing_mod._state.tracer = None

        with patch('builtins.__import__', side_effect=_import_with_missing('opentelemetry')):
            self.assertIsNone(tracing_mod.get_tracer())

        mock_logger.warning.assert_called_once()


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
