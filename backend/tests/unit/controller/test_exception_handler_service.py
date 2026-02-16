"""Unit tests for backend.controller.services.exception_handler_service."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.controller.services.exception_handler_service import (
    ExceptionHandlerService,
    _PASSTHROUGH_EXCEPTIONS,
)
from backend.llm.exceptions import RateLimitError, Timeout


class TestPassthroughList:
    """Validate the passthrough exception tuple makes sense."""

    def test_contains_key_types(self):
        names = {e.__name__ for e in _PASSTHROUGH_EXCEPTIONS}
        assert "Timeout" in names
        assert "RateLimitError" in names
        assert "AuthenticationError" in names
        assert "ContextWindowExceededError" in names

    def test_all_are_exception_subclasses(self):
        for exc_cls in _PASSTHROUGH_EXCEPTIONS:
            assert issubclass(exc_cls, Exception)


class TestExceptionHandlerService:
    @pytest.fixture()
    def ctrl(self):
        c = MagicMock()
        c.id = "test-session"
        c.recovery_service = MagicMock()
        c.recovery_service.react_to_exception = AsyncMock()
        return c

    @pytest.fixture()
    def svc(self, ctrl):
        return ExceptionHandlerService(ctrl)

    async def test_passthrough_exception(self, svc, ctrl):
        exc = Timeout("slow")
        await svc.handle_step_exception(exc)
        ctrl.recovery_service.react_to_exception.assert_awaited_once()
        reported = ctrl.recovery_service.react_to_exception.call_args[0][0]
        assert reported is exc  # same object, not wrapped

    async def test_unknown_exception_wrapped(self, svc, ctrl):
        exc = KeyError("bad key")
        await svc.handle_step_exception(exc)
        ctrl.recovery_service.react_to_exception.assert_awaited_once()
        reported = ctrl.recovery_service.react_to_exception.call_args[0][0]
        assert isinstance(reported, RuntimeError)
        assert "unexpected error" in str(reported)

    async def test_rate_limit_passthrough(self, svc, ctrl):
        exc = RateLimitError("too many")
        await svc.handle_step_exception(exc)
        reported = ctrl.recovery_service.react_to_exception.call_args[0][0]
        assert isinstance(reported, RateLimitError)
