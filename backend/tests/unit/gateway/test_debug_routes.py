"""Tests for backend.gateway.routes.debug."""

from __future__ import annotations

from fastapi import HTTPException

from backend.gateway.routes import debug as debug_routes


class TestDebugRoutes:
    async def test_session_debug_disabled_message_uses_app_debug(self):
        original = debug_routes._DEBUG_ENABLED
        debug_routes._DEBUG_ENABLED = False
        try:
            try:
                await debug_routes.session_debug("sid-1")
            except HTTPException as exc:
                assert exc.status_code == 403
                assert exc.detail == "Debug endpoint disabled. Set APP_DEBUG=true to enable."
            else:
                raise AssertionError("Expected HTTPException")
        finally:
            debug_routes._DEBUG_ENABLED = original

    async def test_list_debug_sessions_disabled_message_uses_app_debug(self):
        original = debug_routes._DEBUG_ENABLED
        debug_routes._DEBUG_ENABLED = False
        try:
            try:
                await debug_routes.list_debug_sessions()
            except HTTPException as exc:
                assert exc.status_code == 403
                assert exc.detail == "Debug endpoint disabled. Set APP_DEBUG=true to enable."
            else:
                raise AssertionError("Expected HTTPException")
        finally:
            debug_routes._DEBUG_ENABLED = original