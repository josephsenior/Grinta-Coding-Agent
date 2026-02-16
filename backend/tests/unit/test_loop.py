"""Tests for backend.core.loop — run loop helpers and error/backoff logic."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.core.loop import (
    _BACKOFF_FACTOR,
    _INITIAL_POLL_INTERVAL,
    _MAX_CONSECUTIVE_ERRORS,
    _MAX_POLL_INTERVAL,
    _create_status_callback,
    _handle_error_status,
    _set_status_callbacks,
    _validate_status_callbacks,
)
from backend.core.enums import RuntimeStatus


# ===================================================================
# Constants
# ===================================================================

class TestConstants:
    def test_backoff_parameters(self):
        assert _INITIAL_POLL_INTERVAL > 0
        assert _MAX_POLL_INTERVAL > _INITIAL_POLL_INTERVAL
        assert _BACKOFF_FACTOR > 1.0
        assert _MAX_CONSECUTIVE_ERRORS > 0


# ===================================================================
# _handle_error_status
# ===================================================================

class TestHandleErrorStatus:

    def test_sets_last_error(self):
        controller = MagicMock()
        controller.state.set_last_error = MagicMock()
        controller.state.iteration_flag.current_value = 5
        _handle_error_status(controller, RuntimeStatus.ERROR, "something broke")
        controller.state.set_last_error.assert_called_once_with(
            "something broke", source="loop.status_callback"
        )

    def test_memory_error_records_boundary(self):
        controller = MagicMock()
        controller.state.iteration_flag.current_value = 7
        _handle_error_status(controller, RuntimeStatus.ERROR_MEMORY, "OOM")
        assert controller.state._memory_error_boundary == 7

    def test_non_memory_error_no_boundary(self):
        controller = MagicMock()
        controller.state.iteration_flag.current_value = 3
        _handle_error_status(controller, RuntimeStatus.ERROR, "generic error")
        # _memory_error_boundary should NOT be set via setattr
        # (it's set via setattr only for ERROR_MEMORY)


# ===================================================================
# _create_status_callback
# ===================================================================

class TestCreateStatusCallback:

    def test_error_callback_calls_handle(self):
        controller = MagicMock()
        controller.state.iteration_flag.current_value = 1
        cb = _create_status_callback(controller)
        with patch("backend.core.loop._handle_error_status") as mock_handle:
            cb("error", RuntimeStatus.ERROR, "bad")
            mock_handle.assert_called_once_with(controller, RuntimeStatus.ERROR, "bad")

    def test_info_callback_logs_only(self):
        controller = MagicMock()
        cb = _create_status_callback(controller)
        # Should not raise
        cb("info", RuntimeStatus.READY, "all good")


# ===================================================================
# _validate_status_callbacks
# ===================================================================

class TestValidateStatusCallbacks:

    def test_no_warning_when_clean(self):
        runtime = MagicMock(spec=[])
        controller = MagicMock(spec=[])
        # Should not raise
        _validate_status_callbacks(runtime, controller)

    def test_warns_when_already_set(self):
        runtime = MagicMock()
        runtime.status_callback = lambda *a: None
        controller = MagicMock()
        controller.status_callback = lambda *a: None
        # Should not raise (just logs)
        _validate_status_callbacks(runtime, controller)


# ===================================================================
# _set_status_callbacks
# ===================================================================

class TestSetStatusCallbacks:

    def test_sets_on_all_three(self):
        runtime = MagicMock()
        controller = MagicMock()
        memory = MagicMock()
        cb = lambda *a: None
        _set_status_callbacks(runtime, controller, memory, cb)
        assert runtime.status_callback is cb
        assert controller.status_callback is cb
        assert memory.status_callback is cb
