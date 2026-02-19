"""Tests for backend.server.services.raw_event_service module.

Targets the 72.7% (8 missed lines) coverage gap.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import status

from backend.server.services import raw_event_service


@pytest.mark.asyncio
class TestDispatchRawMessageEvent:
    @patch("backend.server.services.raw_event_service.require_conversation_manager")
    @patch("backend.server.services.raw_event_service.require_event_service_adapter")
    async def test_empty_body_returns_400(self, mock_adapter, mock_manager):
        response = await raw_event_service.dispatch_raw_message_event(
            conversation_id="c1",
            user_id="u1",
            raw_body="",
            create_if_missing=False,
            conversation_store=None
        )
        assert response.status_code == 400
        assert response.body == b'{"error":"Empty body"}'

    @patch("backend.server.services.raw_event_service.require_conversation_manager")
    @patch("backend.server.services.raw_event_service.require_event_service_adapter")
    async def test_conversation_missing_no_create_returns_404(self, mock_adapter, mock_manager):
        mock_mgr = MagicMock()
        mock_mgr.attach_to_conversation = AsyncMock(return_value=None)
        mock_manager.return_value = mock_mgr

        response = await raw_event_service.dispatch_raw_message_event(
            conversation_id="c1",
            user_id="u1",
            raw_body="hello",
            create_if_missing=False,
            conversation_store=None
        )
        assert response.status_code == 404
        assert b"no_conversation:c1" in response.body

    @patch("backend.server.services.raw_event_service.require_conversation_manager")
    @patch("backend.server.services.raw_event_service.require_event_service_adapter")
    async def test_create_if_missing_but_no_store_returns_500(self, mock_adapter, mock_manager):
        mock_mgr = MagicMock()
        mock_mgr.attach_to_conversation = AsyncMock(return_value=None)
        mock_manager.return_value = mock_mgr

        response = await raw_event_service.dispatch_raw_message_event(
            conversation_id="c1",
            user_id="u1",
            raw_body="hello",
            create_if_missing=True,
            conversation_store=None
        )
        assert response.status_code == 500
        assert b"Conversation store unavailable" in response.body

    @patch("backend.server.services.raw_event_service.require_conversation_manager")
    @patch("backend.server.services.raw_event_service.require_event_service_adapter")
    async def test_creates_conversation_and_attaches(self, mock_adapter, mock_manager):
        mock_mgr = MagicMock()
        mock_conv = MagicMock()
        mock_conv.sid = "sid-123"
        # First call returns None, second call returns mock_conv
        mock_mgr.attach_to_conversation = AsyncMock(side_effect=[None, mock_conv])
        mock_mgr.send_event_to_conversation = AsyncMock()
        mock_manager.return_value = mock_mgr

        mock_store = MagicMock()
        mock_store.save_metadata = AsyncMock()

        response = await raw_event_service.dispatch_raw_message_event(
            conversation_id="c1",
            user_id="u1",
            raw_body="hello",
            create_if_missing=True,
            conversation_store=mock_store
        )
        assert response.status_code == 200
        mock_store.save_metadata.assert_called_once()
        assert mock_mgr.attach_to_conversation.call_count == 2

    @patch("backend.server.services.raw_event_service.require_conversation_manager")
    @patch("backend.server.services.raw_event_service.require_event_service_adapter")
    async def test_runtime_error_not_no_conversation_bubbles_up(self, mock_adapter, mock_manager):
        mock_mgr = MagicMock()
        mock_conv = MagicMock()
        mock_conv.sid = "sid-123"
        mock_mgr.attach_to_conversation = AsyncMock(return_value=mock_conv)
        mock_mgr.send_event_to_conversation = AsyncMock(side_effect=RuntimeError("something else"))
        mock_manager.return_value = mock_mgr

        with pytest.raises(RuntimeError, match="something else"):
            await raw_event_service.dispatch_raw_message_event(
                conversation_id="c1",
                user_id="u1",
                raw_body="hello",
                create_if_missing=False,
                conversation_store=None
            )

    @patch("backend.server.services.raw_event_service.require_conversation_manager")
    @patch("backend.server.services.raw_event_service.require_event_service_adapter")
    async def test_runtime_error_no_conversation_persists_directly(self, mock_adapter, mock_manager):
        mock_mgr = MagicMock()
        mock_conv = MagicMock()
        mock_conv.sid = "sid-123"
        mock_mgr.attach_to_conversation = AsyncMock(return_value=mock_conv)
        mock_mgr.send_event_to_conversation = AsyncMock(side_effect=RuntimeError("no_conversation:c1"))
        mock_manager.return_value = mock_mgr

        mock_adapt = MagicMock()
        mock_stream = MagicMock()
        mock_adapt.get_event_stream.return_value = mock_stream
        mock_adapter.return_value = mock_adapt

        response = await raw_event_service.dispatch_raw_message_event(
            conversation_id="c1",
            user_id="u1",
            raw_body="hello",
            create_if_missing=False,
            conversation_store=None
        )
        assert response.status_code == 200
        assert b"persisted_to_event_store" in response.body
        mock_adapt.start_session.assert_called_once()
        mock_stream.add_event.assert_called_once()
