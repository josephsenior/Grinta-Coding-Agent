"""Tests for backend.execution.utils.log_capture — log output capture."""

from __future__ import annotations

import logging

import pytest

from backend.execution.utils.log_capture import capture_logs


class TestCaptureLogs:
    async def test_captures_error_logs(self):
        logger = logging.getLogger('test.capture.error')
        async with capture_logs('test.capture.error', level=logging.ERROR) as buf:
            logger.error('boom!')
        assert 'boom!' in buf.getvalue()

    async def test_does_not_capture_below_level(self):
        logger = logging.getLogger('test.capture.below')
        async with capture_logs('test.capture.below', level=logging.ERROR) as buf:
            logger.info('info message')
        assert buf.getvalue() == ''

    async def test_restores_original_handlers(self):
        logger = logging.getLogger('test.capture.restore')
        original_handlers = logger.handlers[:]
        original_level = logger.level
        async with capture_logs('test.capture.restore'):
            pass
        assert logger.handlers == original_handlers
        assert logger.level == original_level

    async def test_captures_warning_when_set(self):
        logger = logging.getLogger('test.capture.warn')
        async with capture_logs('test.capture.warn', level=logging.WARNING) as buf:
            logger.warning('careful!')
        assert 'careful!' in buf.getvalue()

    async def test_restores_after_exception(self):
        logger = logging.getLogger('test.capture.exc')
        original_handlers = logger.handlers[:]
        with pytest.raises(ValueError):
            async with capture_logs('test.capture.exc'):
                raise ValueError('oops')
        assert logger.handlers == original_handlers
