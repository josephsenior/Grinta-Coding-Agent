"""Integration tests for conversation CRUD route handlers."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from starlette.requests import Request

from backend.api.routes.manage_conversations import (
    ConversationResponse,
    InitSessionRequest,
    UpdateConversationRequest,
    _delete_conversation_route,
    _get_conversation_route,
    new_conversation,
    search_conversations_route,
    update_conversation,
)
from backend.storage.data_models.conversation_metadata import ConversationTrigger
from backend.storage.data_models.conversation_status import ConversationStatus


def _request(path: str = "/api/conversations") -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": path,
            "headers": [],
            "query_string": b"",
            "client": ("127.0.0.1", 12345),
            "server": ("testserver", 80),
            "scheme": "http",
        }
    )


@pytest.mark.asyncio
async def test_create_conversation_handler_success() -> None:
    req = _request("/api/conversations")
    payload = InitSessionRequest.model_validate({"initial_user_msg": "hello"})

    with (
        patch(
            "backend.api.routes.manage_conversations.extract_request_data",
            return_value=(
                None,
                None,
                "hello",
                None,
                None,
                None,
                None,
                None,
                None,
            ),
        ),
        patch(
            "backend.api.routes.manage_conversations.determine_conversation_trigger",
            return_value=(ConversationTrigger.GUI, None, None),
        ),
        patch(
            "backend.api.routes.manage_conversations.apply_conversation_overrides",
            return_value=(None, None, "hello"),
        ),
        patch(
            "backend.api.routes.manage_conversations.validate_remote_api_request",
            return_value=None,
        ),
        patch(
            "backend.api.routes.manage_conversations.prepare_conversation_params",
            return_value=("user-1", {}, None),
        ),
        patch(
            "backend.api.routes.manage_conversations.resolve_conversation_id",
            return_value="conv-1",
        ),
        patch(
            "backend.api.routes.manage_conversations.handle_regular_conversation",
            AsyncMock(return_value=SimpleNamespace(status=ConversationStatus.STARTING)),
        ),
    ):
        response = await new_conversation(
            request=req,
            data=payload,
            user_id="user-1",
            provider_tokens={},
            user_secrets=None,
            settings=MagicMock(),
        )

    assert isinstance(response, ConversationResponse)
    assert response.status == "ok"
    assert response.conversation_id == "conv-1"
    assert response.conversation_status == ConversationStatus.STARTING


@pytest.mark.asyncio
async def test_search_conversations_handler_success() -> None:
    req = _request("/api/conversations")
    expected: dict[str, object] = {"results": [], "next_page_id": None}

    with (
        patch(
            "backend.api.routes.manage_conversations.get_user_id",
            AsyncMock(return_value="user-1"),
        ),
        patch(
            "backend.api.routes.manage_conversations.get_conversation_store",
            AsyncMock(return_value=MagicMock()),
        ),
        patch(
            "backend.api.routes.manage_conversations._search_conversations_impl",
            AsyncMock(return_value=expected),
        ) as search_impl,
    ):
        response = await search_conversations_route(request=req, page_id=None, limit=20)

    assert response == expected
    search_impl.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_update_delete_handlers() -> None:
    req = _request("/api/conversations/conv-1")
    store = MagicMock()

    metadata = SimpleNamespace(
        user_id="user-1",
        title="Old title",
        last_updated_at=datetime.now(UTC),
    )
    store.get_metadata = AsyncMock(return_value=metadata)
    store.save_metadata = AsyncMock()

    with (
        patch(
            "backend.api.routes.manage_conversations.get_user_id",
            AsyncMock(return_value="user-1"),
        ),
        patch(
            "backend.api.routes.manage_conversations.get_conversation_store",
            AsyncMock(return_value=store),
        ),
        patch(
            "backend.api.routes.manage_conversations.get_conversation_details",
            AsyncMock(return_value={"conversation_id": "conv-1"}),
        ) as get_impl,
        patch(
            "backend.api.routes.manage_conversations.delete_conversation_entry",
            AsyncMock(return_value=True),
        ) as delete_impl,
        patch(
            "backend.api.routes.manage_conversations._resolve_conversation_store",
            AsyncMock(return_value=store),
        ),
        patch(
            "backend.api.routes.manage_conversations._get_conversation_manager_instance",
            return_value=None,
        ),
    ):
        get_result = await _get_conversation_route(req, conversation_id="conv-1")
        update_result = await update_conversation(
            data=UpdateConversationRequest(title="New title"),
            conversation_id="conv-1",
            user_id="user-1",
            conversation_store=store,
        )
        delete_result = await _delete_conversation_route(req, conversation_id="conv-1")

    assert get_result == {"conversation_id": "conv-1"}
    assert update_result is True
    assert delete_result is True
    get_impl.assert_awaited_once()
    delete_impl.assert_awaited_once()
    store.save_metadata.assert_awaited_once()
