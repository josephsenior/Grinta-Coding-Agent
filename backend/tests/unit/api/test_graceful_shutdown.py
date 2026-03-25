"""Tests for backend.api.graceful_shutdown module."""

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def _reset_shutdown_state():
    """Reset module-level shutdown state between tests."""
    import backend.api.graceful_shutdown as mod

    original_handlers = mod._shutdown_handlers[:]
    original_in_progress = mod._shutdown_in_progress
    mod._shutdown_handlers.clear()
    mod._shutdown_in_progress = False
    yield
    mod._shutdown_handlers[:] = original_handlers
    mod._shutdown_in_progress = original_in_progress


class TestRegisterShutdownHandler:
    def test_register_sync_handler(self):
        from backend.api.graceful_shutdown import (
            _shutdown_handlers,
            register_shutdown_handler,
        )

        handler = MagicMock()
        register_shutdown_handler(handler)
        assert handler in _shutdown_handlers

    def test_register_multiple_handlers(self):
        from backend.api.graceful_shutdown import (
            _shutdown_handlers,
            register_shutdown_handler,
        )

        h1, h2, h3 = MagicMock(), MagicMock(), MagicMock()
        register_shutdown_handler(h1)
        register_shutdown_handler(h2)
        register_shutdown_handler(h3)
        assert len(_shutdown_handlers) == 3
        assert _shutdown_handlers == [h1, h2, h3]


class TestGracefulShutdown:
    async def test_calls_sync_handler(self):
        from backend.api.graceful_shutdown import (
            graceful_shutdown,
            register_shutdown_handler,
        )

        handler = MagicMock()
        handler.__name__ = "test_sync"
        register_shutdown_handler(handler)
        await graceful_shutdown()
        handler.assert_called_once()

    async def test_calls_async_handler(self):
        from backend.api.graceful_shutdown import (
            graceful_shutdown,
            register_shutdown_handler,
        )

        called = False

        async def async_handler():
            nonlocal called
            called = True

        register_shutdown_handler(async_handler)
        await graceful_shutdown()
        assert called is True

    async def test_skips_if_already_in_progress(self):
        import backend.api.graceful_shutdown as mod
        from backend.api.graceful_shutdown import (
            graceful_shutdown,
            register_shutdown_handler,
        )

        handler = MagicMock()
        handler.__name__ = "test_handler"
        register_shutdown_handler(handler)
        mod._shutdown_in_progress = True
        await graceful_shutdown()
        handler.assert_not_called()

    async def test_handler_exception_does_not_stop_others(self):
        from backend.api.graceful_shutdown import (
            graceful_shutdown,
            register_shutdown_handler,
        )

        bad_handler = MagicMock(side_effect=RuntimeError("boom"))
        bad_handler.__name__ = "bad_handler"
        good_handler = MagicMock()
        good_handler.__name__ = "good_handler"
        register_shutdown_handler(bad_handler)
        register_shutdown_handler(good_handler)
        await graceful_shutdown()
        bad_handler.assert_called_once()
        good_handler.assert_called_once()

    async def test_sets_in_progress_flag(self):
        import backend.api.graceful_shutdown as mod
        from backend.api.graceful_shutdown import graceful_shutdown

        assert mod._shutdown_in_progress is False
        await graceful_shutdown()
        assert mod._shutdown_in_progress is True

    async def test_no_handlers_completes_ok(self):
        from backend.api.graceful_shutdown import graceful_shutdown

        await graceful_shutdown()  # should not raise


class TestGracefulShutdownRequestsProcessShutdown:
    async def test_calls_request_process_shutdown(self):
        from backend.api.graceful_shutdown import graceful_shutdown

        with patch("backend.utils.shutdown_listener.request_process_shutdown") as rps:
            await graceful_shutdown()
            rps.assert_called_once()
