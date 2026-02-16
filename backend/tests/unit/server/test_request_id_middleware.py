"""Tests for backend.server.middleware.request_id — RequestIDMiddleware & get_request_id."""

from __future__ import annotations

from unittest.mock import MagicMock


from backend.server.middleware.request_id import (
    get_request_id,
)


class TestGetRequestId:
    def test_returns_request_id_from_state(self):
        req = MagicMock()
        req.state.request_id = "abc-123"
        assert get_request_id(req) == "abc-123"

    def test_returns_unknown_when_no_state(self):
        """When request has no .state attribute at all, returns 'unknown'."""
        req = MagicMock(spec=[])
        # spec=[] means accessing .state raises AttributeError
        assert get_request_id(req) == "unknown"

    def test_returns_unknown_when_no_request_id(self):
        req = MagicMock()
        del req.state.request_id
        assert get_request_id(req) == "unknown"
