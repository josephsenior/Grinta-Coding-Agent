"""Comprehensive coverage gaps for backend.utils."""

from __future__ import annotations

import asyncio
import importlib
import unittest.mock
from typing import Any, cast

import pytest

import backend.utils.async_utils as async_utils
import backend.utils.circuit_breaker as circuit_breaker
import backend.utils.import_utils as import_utils
import backend.utils.tenacity_metrics as tenacity_metrics
import backend.utils.tenacity_stop as tenacity_stop


class TestImportUtilsFinal:
    """Test missing branches in import_utils."""

    def test_get_impl_mro_match_true(self):
        """Covers lines 78, 81 (returning True from MRO match)."""

        class Base:
            pass

        Base.__module__ = 'mod'
        Base.__name__ = 'Name'

        class SameNameBase:
            pass

        SameNameBase.__module__ = 'mod'
        SameNameBase.__name__ = 'Name'

        class Impl(SameNameBase):
            pass

        assert import_utils._impl_matches_base(Base, Impl) is True


class TestAsyncUtilsFinal:
    """Test missing branches in async_utils."""

    @pytest.mark.asyncio
    async def test_handle_pending_tasks_logging_empty(self):
        """Covers line 101 (logging with no pending info)."""
        done: set[asyncio.Task[Any]] = set()
        pending: set[asyncio.Task[Any]] = {
            cast(asyncio.Task[Any], unittest.mock.MagicMock(spec=asyncio.Task))
        }
        pending_task = list(pending)[0]
        cast(
            Any, pending_task
        ).get_coro.return_value = None  # Force "Unable to get task names"

        with unittest.mock.patch('logging.getLogger') as mock_logger:
            async_utils._handle_pending_tasks(done, pending)
            mock_logger.return_value.error.assert_called()


class TestCircuitBreakerFinal:
    """Extra gaps for circuit_breaker."""

    @pytest.mark.asyncio
    async def test_half_open_probes_exhausted(self):
        """Covers lines 48-49."""
        cb = circuit_breaker.CircuitBreaker('test')
        cb.state.state = 'half_open'
        cb.state.half_open_probes_left = 0

        async def dummy():
            return 'ok'

        with pytest.raises(RuntimeError, match='circuit_half_open_block'):
            await cb.async_call(dummy)

    @pytest.mark.asyncio
    async def test_on_close_success_metric(self):
        """Covers line 176 (on_close_success)."""
        cb = circuit_breaker.CircuitBreaker('test')
        cb.state.state = 'half_open'
        cb.state.half_open_probes_left = 1

        async def success():
            return 'ok'

        with unittest.mock.patch(
            'backend.utils.circuit_breaker._CB_METRICS'
        ) as mock_metrics:
            await cb.async_call(success)
            mock_metrics.on_close_success.assert_called_with('test')


class TestSearchUtilsFinal:
    """Extra gaps for search_utils."""

    def test_page_id_to_offset_invalid_format(self):
        """Covers line 49."""
        from backend.utils.search_utils import page_id_to_offset

        assert page_id_to_offset('not-base64-json!!!') == 0


class TestShutdownFinal:
    """Extra gaps for shutdown_listener."""

    def test_request_process_shutdown_noop_when_already_exiting(self):
        import backend.utils.shutdown_listener as mod
        from backend.utils.shutdown_listener import (
            add_shutdown_listener,
            remove_shutdown_listener,
            request_process_shutdown,
        )

        mod._should_exit = True
        listener = unittest.mock.MagicMock()
        lid = add_shutdown_listener(listener)
        try:
            request_process_shutdown()
        finally:
            remove_shutdown_listener(lid)
            mod._should_exit = False
        listener.assert_not_called()


class TestTenacityStopFinal:
    """Covers tenacity_stop gaps."""

    def test_stop_if_should_exit_exception(self):
        """Covers lines 33-37 (exception handling in mod.should_exit)."""
        stop_cond = tenacity_stop.stop_if_should_exit()

        def side_effect(name):
            if name == 'backend.utils.tenacity_stop':
                m = unittest.mock.MagicMock()
                m.should_exit.side_effect = RuntimeError('fail')
                return m
            return importlib.import_module(name)

        with unittest.mock.patch('importlib.import_module', side_effect=side_effect):
            # local fallback should return False (by default)
            assert stop_cond(cast(Any, unittest.mock.MagicMock())) is False

    def test_stop_if_should_exit_local_fallback(self):
        """Covers line 35 (local fallback via globals)."""
        stop_cond = tenacity_stop.stop_if_should_exit()

        # Inject a callable into the module's globals so the local fallback fires
        sentinel = lambda: True  # noqa: E731
        tenacity_stop.should_exit = sentinel  # type: ignore[attr-defined]
        try:

            def side_effect_mock(name):
                if name == 'backend.utils.tenacity_stop':
                    m = unittest.mock.MagicMock()
                    m.should_exit.side_effect = Exception('fail')
                    return m
                return importlib.import_module(name)

            with unittest.mock.patch(
                'importlib.import_module', side_effect=side_effect_mock
            ):
                assert stop_cond(cast(Any, unittest.mock.MagicMock())) is True
        finally:
            del tenacity_stop.should_exit  # type: ignore[attr-defined]


class TestPromptFinal:
    """Covers prompt.py gaps."""

    def test_add_turns_left_reminder_no_text_content(self):
        """Covers lines 243-244 (Message with no TextContent)."""
        from backend.core.message import ImageContent, Message
        from backend.utils.prompt import PromptManager

        pm = unittest.mock.MagicMock(spec=PromptManager)

        msg = Message(
            role='user',
            content=[ImageContent(image_urls=['http://example.com/img.png'])],
        )
        state = unittest.mock.MagicMock()
        PromptManager.add_turns_left_reminder(pm, [msg], state)


class TestTenacityMetricsFinal:
    """Covers tenacity_metrics gaps."""

    def test_tenacity_before_sleep_exception(self):
        """Covers lines 57-72 (exception in _before_sleep)."""
        hook = tenacity_metrics.tenacity_before_sleep_factory('op')
        hook(cast(Any, None))

    def test_tenacity_after_exception_in_sanitize(self):
        """Covers lines 95-100 (exception in _after start)."""
        hook = tenacity_metrics.tenacity_after_factory('op')
        with unittest.mock.patch(
            'backend.utils.tenacity_metrics.sanitize_operation_label',
            side_effect=Exception,
        ):
            hook(unittest.mock.MagicMock())

    def test_tenacity_after_failed_outcome_check(self):
        """Covers lines 128-129 (final catch-all)."""
        hook = tenacity_metrics.tenacity_after_factory('op')
        rs = unittest.mock.MagicMock()
        rs.outcome = 'not an object'
        hook(rs)
