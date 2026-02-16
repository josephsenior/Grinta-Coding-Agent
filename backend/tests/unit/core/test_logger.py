"""Tests for backend.core.logger — RollingLogger, trace context, ForgeLoggerAdapter, etc."""

from __future__ import annotations

import os
import logging
from unittest.mock import patch, MagicMock, PropertyMock


from backend.core.logger import (
    ForgeLoggerAdapter,
    LlmFileHandler,
    RollingLogger,
    bind_context,
    clear_trace_context,
    get_console_handler,
    get_file_handler,
    get_trace_context,
    json_formatter,
    json_log_handler,
    log_uncaught_exceptions,
    set_trace_context,
)


# ── RollingLogger ─────────────────────────────────────────────────────

class TestRollingLogger:
    def test_initialization(self):
        rl = RollingLogger(max_lines=5, char_limit=40)
        assert rl.max_lines == 5
        assert rl.char_limit == 40
        assert len(rl.log_lines) == 5
        assert rl.all_lines == ""

    @patch("backend.core.logger.DEBUG", False)
    def test_is_enabled_false_when_no_debug(self):
        rl = RollingLogger()
        assert rl.is_enabled() is False

    @patch("backend.core.logger.DEBUG", True)
    @patch("sys.stdout")
    def test_is_enabled_requires_tty(self, mock_stdout):
        mock_stdout.isatty.return_value = False
        rl = RollingLogger()
        assert rl.is_enabled() is False

    def test_add_line_updates_buffer(self):
        rl = RollingLogger(max_lines=3, char_limit=100)
        with patch.object(rl, "print_lines"):
            rl.add_line("hello")
        assert rl.log_lines[-1] == "hello"
        assert "hello\n" in rl.all_lines

    def test_add_line_truncates_long_lines(self):
        rl = RollingLogger(max_lines=3, char_limit=5)
        with patch.object(rl, "print_lines"):
            rl.add_line("abcdefghij")
        assert rl.log_lines[-1] == "abcde"

    def test_add_line_shifts_buffer(self):
        rl = RollingLogger(max_lines=2, char_limit=100)
        with patch.object(rl, "print_lines"):
            rl.add_line("first")
            rl.add_line("second")
            rl.add_line("third")
        assert rl.log_lines == ["second", "third"]

    @patch("backend.core.logger.DEBUG", True)
    @patch("sys.stdout")
    def test_rolling_logger_display_logic(self, mock_stdout):
        mock_stdout.isatty.return_value = True
        rl = RollingLogger(max_lines=2, char_limit=10)
        
        # Test start
        rl.start("Starting...")
        assert mock_stdout.write.call_count >= 1
        
        # Test add_line (which calls print_lines, move_back, replace_current_line)
        mock_stdout.write.reset_mock()
        rl.add_line("test")
        
        # Should have called write multiple times for escape codes and content
        # \x1b[F (move back)
        # \x1b[2K (replace line)
        assert any("\x1b[F" in call.args[0] for call in mock_stdout.write.call_args_list)
        assert any("\x1b[2K" in call.args[0] for call in mock_stdout.write.call_args_list)
        assert any("test" in call.args[0] for call in mock_stdout.write.call_args_list)

    @patch("backend.core.logger.DEBUG", True)
    @patch("sys.stdout")
    def test_write_immediately(self, mock_stdout):
        mock_stdout.isatty.return_value = True
        rl = RollingLogger()
        rl.write_immediately("immediate")
        mock_stdout.write.assert_called_with("immediate")
        mock_stdout.flush.assert_called()

    @patch("backend.core.logger.DEBUG", False)
    @patch("sys.stdout")
    def test_is_disabled_no_write(self, mock_stdout):
        mock_stdout.isatty.return_value = True
        rl = RollingLogger()
        rl._write("should not write")
        mock_stdout.write.assert_not_called()
        rl._flush()
        mock_stdout.flush.assert_not_called()


# ── Trace context ─────────────────────────────────────────────────────

class TestTraceContext:
    def test_set_and_get_context(self):
        set_trace_context({"trace_id": "abc"})
        ctx = get_trace_context()
        assert ctx == {"trace_id": "abc"}
        clear_trace_context()

    def test_clear_context(self):
        set_trace_context({"x": 1})
        clear_trace_context()
        assert get_trace_context() == {}

    def test_set_none_clears_context(self):
        set_trace_context({"x": 1})
        set_trace_context(None)
        assert get_trace_context() == {}

    def test_get_returns_copy(self):
        set_trace_context({"key": "value"})
        ctx1 = get_trace_context()
        ctx2 = get_trace_context()
        assert ctx1 == ctx2
        ctx1["key"] = "mutated"
        assert get_trace_context()["key"] == "value"
        clear_trace_context()


# ── ForgeLoggerAdapter ────────────────────────────────────────────────

class TestForgeLoggerAdapter:
    def test_default_extra(self):
        adapter = ForgeLoggerAdapter()
        assert adapter.extra == {}

    def test_bind_returns_new_adapter(self):
        adapter = ForgeLoggerAdapter()
        bound = adapter.bind(trace_id="abc", step_id="s1")
        assert isinstance(bound, ForgeLoggerAdapter)
        assert bound.extra == {"trace_id": "abc", "step_id": "s1"}
        assert adapter.extra == {}  # Original unchanged

    def test_bind_merges_context(self):
        adapter = ForgeLoggerAdapter(extra={"trace_id": "a"})
        bound = adapter.bind(step_id="s1")
        assert bound.extra == {"trace_id": "a", "step_id": "s1"}

    def test_bind_override_existing(self):
        adapter = ForgeLoggerAdapter(extra={"trace_id": "old"})
        bound = adapter.bind(trace_id="new")
        assert bound.extra["trace_id"] == "new"

    def test_process_merges_extra_in_kwargs(self):
        adapter = ForgeLoggerAdapter(extra={"trace_id": "abc"})
        msg, kwargs = adapter.process("test", {"extra": {"step_id": "s1"}})
        assert kwargs["extra"] == {"trace_id": "abc", "step_id": "s1"}

    def test_process_sets_extra_when_missing(self):
        adapter = ForgeLoggerAdapter(extra={"trace_id": "abc"})
        msg, kwargs = adapter.process("test", {})
        assert kwargs["extra"] == {"trace_id": "abc"}


# ── bind_context helper ──────────────────────────────────────────────

class TestBindContext:
    def test_with_raw_logger(self):
        logger = logging.getLogger("test_bind")
        adapter = bind_context(logger, trace_id="t1")
        assert isinstance(adapter, ForgeLoggerAdapter)
        assert adapter.extra["trace_id"] == "t1"

    def test_with_adapter(self):
        adapter = ForgeLoggerAdapter(extra={"trace_id": "old"})
        new_adapter = bind_context(adapter, step_id="s2")
        assert new_adapter.extra == {"trace_id": "old", "step_id": "s2"}


# ── Handler factories ────────────────────────────────────────────────

class TestHandlerFactories:
    def test_get_console_handler(self):
        handler = get_console_handler(logging.DEBUG)
        assert isinstance(handler, logging.StreamHandler)
        assert handler.level == logging.DEBUG

    def test_get_file_handler(self, tmp_path):
        handler = get_file_handler(str(tmp_path), logging.WARNING)
        assert handler.level == logging.WARNING
        handler.close()

    def test_json_formatter_returns_formatter(self):
        fmt = json_formatter()
        from pythonjsonlogger.json import JsonFormatter
        assert isinstance(fmt, JsonFormatter)

    def test_json_log_handler(self):
        handler = json_log_handler(logging.ERROR)
        assert isinstance(handler, logging.Handler)
        assert handler.level == logging.ERROR


# ── log_uncaught_exceptions ───────────────────────────────────────────

class TestLogUncaughtExceptions:
    @patch("backend.core.logger.logging")
    def test_logs_exception(self, mock_logging):
        try:
            raise ValueError("test error")
        except ValueError:
            import sys
            _, exc, tb = sys.exc_info()
            log_uncaught_exceptions(ValueError, exc, tb)
        mock_logging.error.assert_called()


# ── LlmFileHandler ───────────────────────────────────────────────────

class TestLlmFileHandler:
    def test_message_counter_increments(self, tmp_path):
        with patch("backend.core.logger.LOG_DIR", str(tmp_path)):
            handler = LlmFileHandler("prompt", delay=True)
            assert handler.message_counter == 1
            record = logging.LogRecord(
                name="test", level=logging.INFO, pathname="", lineno=0,
                msg="test message", args=None, exc_info=None,
            )
            handler.emit(record)
            assert handler.message_counter == 2
            # Stream is already closed by emit(); just remove the handler
            # to avoid ValueError on flush of closed file.
            handler.stream = None

# ── Trace context Errors ─────────────────────────────────────────────

class TestTraceContextErrors:
    def test_set_context_exception_handled(self):
        with patch("backend.core.logger._TRACE_LOCAL", spec=[]): # Triggers AttributeError/Exception
            # Should not raise
            set_trace_context({"a": 1})

    def test_clear_context_exception_handled(self):
        with patch("backend.core.logger._TRACE_LOCAL", spec=[]):
            # Should not raise
            clear_trace_context()

    def test_get_context_exception_handled(self):
        with patch("backend.core.logger._TRACE_LOCAL", spec=[]):
            # Should return empty dict
            assert get_trace_context() == {}


# ── LlmFileHandler Extra ──────────────────────────────────────────────

class TestLlmFileHandlerExtra:
    @patch("backend.core.logger.DEBUG", False)
    def test_initialization_no_debug(self, tmp_path):
        # Create a dummy file in the directory to test unlinking
        session_dir = os.path.join(tmp_path, "llm", "default")
        os.makedirs(session_dir, exist_ok=True)
        dummy_file = os.path.join(session_dir, "old.log")
        with open(dummy_file, "w") as f:
            f.write("old content")
            
        with patch("backend.core.logger.LOG_DIR", str(tmp_path)):
            handler = LlmFileHandler("prompt", delay=True)
            assert handler.session == "default"
            # Should have unlinked the file
            assert not os.path.exists(dummy_file)

    @patch("backend.core.logger.DEBUG", False)
    @patch("os.unlink", side_effect=Exception("unlink failed"))
    def test_initialization_unlink_failure_handled(self, mock_unlink, tmp_path):
        session_dir = os.path.join(tmp_path, "llm", "default")
        os.makedirs(session_dir, exist_ok=True)
        dummy_file = os.path.join(session_dir, "old.log")
        with open(dummy_file, "w") as f:
            f.write("old content")
            
        with patch("backend.core.logger.LOG_DIR", str(tmp_path)):
            # Should not raise
            handler = LlmFileHandler("prompt", delay=True)
            assert os.path.exists(dummy_file)

    @patch("backend.core.logger.DEBUG", True)
    def test_initialization_debug(self, tmp_path):
        with patch("backend.core.logger.LOG_DIR", str(tmp_path)):
            handler = LlmFileHandler("prompt", delay=True)
            assert handler.session != "default"
            assert len(handler.session) > 0

    def test_emit_logic(self, tmp_path):
        with patch("backend.core.logger.LOG_DIR", str(tmp_path)):
            handler = LlmFileHandler("prompt", delay=True)
            record = logging.LogRecord(
                name="test", level=logging.INFO, pathname="", lineno=0,
                msg="test message", args=None, exc_info=None,
            )
            handler.emit(record)
            
            # Check file exists
            log_file = os.path.join(handler.log_directory, "prompt_001.log")
            assert os.path.exists(log_file)
            with open(log_file, "r") as f:
                assert "test message" in f.read()


# ── Extra Coverage ────────────────────────────────────────────────────

class TestLoggerExtraCoverage:
    def test_get_file_handler_json(self, tmp_path):
        with patch("backend.core.logger.LOG_JSON", True):
            handler = get_file_handler(str(tmp_path), logging.INFO)
            from pythonjsonlogger.json import JsonFormatter
            assert isinstance(handler.formatter, JsonFormatter)
            handler.close()

    def test_log_uncaught_exceptions_no_tb(self):
        with patch("backend.core.logger.logging") as mock_logging:
            err = ValueError("test")
            log_uncaught_exceptions(ValueError, err, None)
            mock_logging.error.assert_called_with("%s: %s", ValueError, err)

    def test_bind_context_recursive(self):
        adapter = ForgeLoggerAdapter(extra={"a": 1})
        bound = bind_context(adapter, b=2)
        assert bound.extra == {"a": 1, "b": 2}
        
        # Test with raw logger again to be sure
        logger = logging.getLogger("raw")
        bound2 = bind_context(logger, c=3)
        assert bound2.extra == {"c": 3}
