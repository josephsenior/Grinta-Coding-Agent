"""Tests for backend.core.log_formatters — formatters, filters, and strip_ansi."""

from __future__ import annotations

import logging
import os
import sys
import types
from unittest.mock import patch

from backend.core.log_formatters import (
    _TRACE_LOCAL,
    ColoredFormatter,
    EnhancedJSONFormatter,
    NoColorFormatter,
    OpenTelemetryTraceFilter,
    SensitiveDataFilter,
    StackInfoFilter,
    TraceContextFilter,
    _fix_record,
    strip_ansi,
)

# ===================================================================
# strip_ansi
# ===================================================================


class TestStripAnsi:
    def test_removes_basic_color(self):
        assert strip_ansi('\x1b[31mRed\x1b[0m') == 'Red'

    def test_removes_bold_and_underline(self):
        assert strip_ansi('\x1b[1mBold\x1b[0m') == 'Bold'

    def test_multi_param_sequence(self):
        assert strip_ansi('\x1b[1;31mBoldRed\x1b[0m') == 'BoldRed'

    def test_no_ansi_unchanged(self):
        assert strip_ansi('plain text') == 'plain text'

    def test_empty_string(self):
        assert strip_ansi('') == ''


# ===================================================================
# _fix_record
# ===================================================================


class TestFixRecord:
    def test_copies_record(self):
        rec = logging.LogRecord('name', logging.INFO, 'file', 1, 'msg', (), None)
        fixed = _fix_record(rec)
        assert fixed is not rec
        assert fixed.msg == 'msg'

    def test_exc_info_true_resolved(self):
        rec = logging.LogRecord('name', logging.ERROR, 'file', 1, 'msg', (), None)
        setattr(rec, 'exc_info', True)
        fixed = _fix_record(rec)
        # Should be replaced with actual sys.exc_info() tuple
        assert fixed.exc_info is not True


# ===================================================================
# StackInfoFilter
# ===================================================================


class TestStackInfoFilter:
    def test_passes_all_records(self):
        f = StackInfoFilter()
        rec = logging.LogRecord('n', logging.DEBUG, 'f', 1, 'm', (), None)
        assert f.filter(rec) is True

    def test_error_record_still_passes(self):
        f = StackInfoFilter()
        rec = logging.LogRecord('n', logging.ERROR, 'f', 1, 'm', (), None)
        assert f.filter(rec) is True

    def test_error_record_sets_stack_info_with_exc_info(self):
        f = StackInfoFilter()
        try:
            raise ValueError('boom')
        except ValueError:
            rec = logging.LogRecord('n', logging.ERROR, 'f', 1, 'm', (), None)
            assert f.filter(rec) is True
            assert rec.stack_info
            assert rec.exc_info


# ===================================================================
# NoColorFormatter
# ===================================================================


class TestNoColorFormatter:
    def test_strips_ansi_from_message(self):
        fmt = NoColorFormatter('%(message)s')
        rec = logging.LogRecord(
            'n', logging.INFO, 'f', 1, '\x1b[31mRed\x1b[0m', (), None
        )
        output = fmt.format(rec)
        assert '\x1b[' not in output
        assert 'Red' in output


# ===================================================================
# EnhancedJSONFormatter
# ===================================================================


class TestEnhancedJSONFormatter:
    def test_adds_standard_fields(self):
        fmt = EnhancedJSONFormatter()
        rec = logging.LogRecord(
            'mylogger', logging.INFO, 'myfile.py', 42, 'hello', (), None
        )
        output = fmt.format(rec)
        # Output should be valid JSON-ish string containing expected keys
        assert 'timestamp' in output
        assert 'thread_name' in output
        assert 'process_id' in output
        assert 'location' in output
        assert 'function' in output

    def test_adds_optional_fields_when_present(self):
        fmt = EnhancedJSONFormatter()
        rec = logging.LogRecord(
            'mylogger', logging.INFO, 'myfile.py', 42, 'hello', (), None
        )
        rec.request_id = 'req-123'
        rec.conversation_id = 'conv-456'
        rec.agent_type = 'Orchestrator'
        rec.action_type = 'run'
        rec.model_used = 'gpt-4'
        rec.tokens_consumed = 100
        rec.cost_usd = 0.05
        rec.duration_ms = 200
        output = fmt.format(rec)
        assert 'req-123' in output
        assert 'conv-456' in output
        assert 'Orchestrator' in output
        assert 'gpt-4' in output


# ===================================================================
# ColoredFormatter
# ===================================================================


class TestColoredFormatter:
    def test_step_message(self):
        fmt = ColoredFormatter()
        rec = logging.LogRecord('n', logging.INFO, 'f', 1, 'Step message', (), None)
        rec.msg_type = 'STEP'
        output = fmt.format(rec)
        assert 'Step message' in output

    def test_step_message_with_all_events(self, monkeypatch):
        monkeypatch.setattr('backend.core.log_formatters.LOG_ALL_EVENTS', True)
        monkeypatch.setattr('backend.core.log_formatters.LOG_COLORS', {})
        fmt = ColoredFormatter()
        rec = logging.LogRecord('n', logging.INFO, 'f', 1, 'Step message', (), None)
        rec.msg_type = 'STEP'
        output = fmt.format(rec)
        assert '==============' in output

    def test_event_source_msg_type_resolution(self, monkeypatch):
        monkeypatch.setattr(
            'backend.core.log_formatters.LOG_COLORS',
            {'AGENT_START': 'cyan'},
        )
        monkeypatch.setattr('backend.core.constants.DISABLE_COLOR_PRINTING', False)
        monkeypatch.setattr(
            'backend.core.log_formatters.colored', lambda text, _c: text
        )
        fmt = ColoredFormatter()
        rec = logging.LogRecord('n', logging.INFO, 'f', 1, 'Hello', (), None)
        rec.msg_type = 'START'
        rec.event_source = 'agent'
        output = fmt.format(rec)
        assert 'AGENT_START' in output

    def test_error_format_includes_location(self, monkeypatch):
        monkeypatch.setattr('backend.core.log_formatters.LOG_COLORS', {'ERROR': 'red'})
        monkeypatch.setattr('backend.core.constants.DISABLE_COLOR_PRINTING', False)
        monkeypatch.setattr(
            'backend.core.log_formatters.colored', lambda text, _c: text
        )
        monkeypatch.setattr('backend.core.constants.DEBUG', False)
        fmt = ColoredFormatter()
        rec = logging.LogRecord('n', logging.ERROR, 'file.py', 12, 'Boom', (), None)
        rec.msg_type = 'ERROR'
        rec.levelname = 'ERROR'
        output = fmt.format(rec)
        assert 'file.py:12' in output

    def test_fallback_for_unknown_msg_type(self):
        fmt = ColoredFormatter()
        rec = logging.LogRecord('n', logging.INFO, 'f', 1, 'Normal message', (), None)
        rec.msg_type = 'UNKNOWN_TYPE_XYZ'
        output = fmt.format(rec)
        assert 'Normal message' in output

    def test_no_msg_type(self):
        fmt = ColoredFormatter()
        rec = logging.LogRecord('n', logging.INFO, 'f', 1, 'Plain', (), None)
        output = fmt.format(rec)
        assert 'Plain' in output


# ===================================================================
# SensitiveDataFilter
# ===================================================================


class TestSensitiveDataFilter:
    def test_redacts_env_key(self):
        f = SensitiveDataFilter()
        with patch.dict(
            os.environ, {'MY_SECRET_KEY': 'supersecretvalue123'}, clear=False
        ):
            rec = logging.LogRecord(
                'n', logging.INFO, 'f', 1, 'Using key supersecretvalue123 now', (), None
            )
            f.filter(rec)
            assert 'supersecretvalue123' not in rec.msg
            assert '******' in rec.msg

    def test_skips_short_values(self):
        f = SensitiveDataFilter()
        with patch.dict(os.environ, {'MY_SECRET_KEY': 'ab'}, clear=False):
            rec = logging.LogRecord(
                'n', logging.INFO, 'f', 1, 'Using key ab now', (), None
            )
            f.filter(rec)
            # Short values (len<=2) should NOT be redacted
            assert 'ab' in rec.msg

    def test_redacts_pattern_in_msg(self):
        f = SensitiveDataFilter()
        rec = logging.LogRecord(
            'n', logging.INFO, 'f', 1, "Setting api_key='sk-test123'", (), None
        )
        f.filter(rec)
        assert 'sk-test123' not in rec.msg
        assert '******' in rec.msg

    def test_redacts_runtime_env_pattern(self):
        f = SensitiveDataFilter()
        rec = logging.LogRecord(
            'n',
            logging.INFO,
            'f',
            1,
            "runtime_env_git_provider_token='secret123'",
            (),
            None,
        )
        f.filter(rec)
        assert 'secret123' not in rec.msg
        assert '******' in rec.msg

    def test_clears_record_args(self):
        f = SensitiveDataFilter()
        rec = logging.LogRecord('n', logging.INFO, 'f', 1, 'msg %s', ('arg',), None)
        f.filter(rec)
        assert rec.args == ()

    def test_always_returns_true(self):
        f = SensitiveDataFilter()
        rec = logging.LogRecord('n', logging.INFO, 'f', 1, 'clean msg', (), None)
        assert f.filter(rec) is True


# ===================================================================
# TraceContextFilter
# ===================================================================


class TestTraceContextFilter:
    def test_injects_trace_context(self):
        f = TraceContextFilter()
        _TRACE_LOCAL.context = {'trace_id': 'abc123', 'span_id': 'def456'}
        try:
            rec = logging.LogRecord('n', logging.INFO, 'f', 1, 'msg', (), None)
            assert f.filter(rec) is True
            assert getattr(rec, 'trace_id') == 'abc123'
            assert getattr(rec, 'span_id') == 'def456'
        finally:
            _TRACE_LOCAL.context = {}

    def test_no_context_set(self):
        f = TraceContextFilter()
        if hasattr(_TRACE_LOCAL, 'context'):
            delattr(_TRACE_LOCAL, 'context')
        rec = logging.LogRecord('n', logging.INFO, 'f', 1, 'msg', (), None)
        assert f.filter(rec) is True

    def test_does_not_overwrite_existing(self):
        f = TraceContextFilter()
        _TRACE_LOCAL.context = {'trace_id': 'new_value'}
        try:
            rec = logging.LogRecord('n', logging.INFO, 'f', 1, 'msg', (), None)
            setattr(rec, 'trace_id', 'original')
            f.filter(rec)
            assert getattr(rec, 'trace_id') == 'original'
        finally:
            _TRACE_LOCAL.context = {}


class TestOpenTelemetryTraceFilter:
    def test_adds_trace_and_span_ids(self, monkeypatch):
        class DummyContext:
            is_valid = True
            trace_id = 123
            span_id = 456

        class DummySpan:
            def get_span_context(self):
                return DummyContext()

        fake_trace = types.SimpleNamespace(get_current_span=lambda: DummySpan())
        monkeypatch.setitem(
            sys.modules, 'opentelemetry', types.SimpleNamespace(trace=fake_trace)
        )

        f = OpenTelemetryTraceFilter()
        rec = logging.LogRecord('n', logging.INFO, 'f', 1, 'msg', (), None)
        assert f.filter(rec) is True
        assert hasattr(rec, 'trace_id')
        assert hasattr(rec, 'span_id')

    def test_skips_invalid_context(self, monkeypatch):
        class DummyContext:
            is_valid = False
            trace_id = 1
            span_id = 2

        class DummySpan:
            def get_span_context(self):
                return DummyContext()

        fake_trace = types.SimpleNamespace(get_current_span=lambda: DummySpan())
        monkeypatch.setitem(
            sys.modules, 'opentelemetry', types.SimpleNamespace(trace=fake_trace)
        )

        f = OpenTelemetryTraceFilter()
        rec = logging.LogRecord('n', logging.INFO, 'f', 1, 'msg', (), None)
        assert f.filter(rec) is True
        assert not hasattr(rec, 'trace_id')
