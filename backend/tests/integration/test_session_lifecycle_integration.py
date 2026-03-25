"""Integration tests for conversation lifecycle handlers (start/stop)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.api.routes.conversation_collection import (
    ConversationResponse,
    ProvidersSetModel,
    start_conversation,
    stop_conversation,
)
from backend.storage.data_models.conversation_status import ConversationStatus


@pytest.mark.asyncio
async def test_start_conversation_success() -> None:
    conversation_id = "conv-start-1"
    user_id = "user-1"

    store = MagicMock()
    store.get_metadata = AsyncMock(return_value=SimpleNamespace(id=conversation_id))

    manager = MagicMock()
    manager.maybe_start_agent_loop = AsyncMock(
        return_value=SimpleNamespace(status=ConversationStatus.RUNNING)
    )

    with (
        patch(
            "backend.api.services.conversation_mutation_service.resolve_conversation_store",
            AsyncMock(return_value=store),
        ),
        patch(
            "backend.api.services.conversation_mutation_service.require_conversation_manager",
            return_value=manager,
        ),
        patch(
            "backend.api.services.conversation_service.setup_init_conversation_settings",
            AsyncMock(return_value=SimpleNamespace()),
        ),
    ):
        response = await start_conversation(
            providers_set=ProvidersSetModel(providers_set=[]),
            conversation_id=conversation_id,
            user_id=user_id,
            provider_tokens=None,
            settings=MagicMock(),
            conversation_store=store,
        )

    assert isinstance(response, ConversationResponse)
    assert response.status == "ok"
    assert response.conversation_id == conversation_id
    assert response.conversation_status == ConversationStatus.RUNNING


@pytest.mark.asyncio
async def test_stop_conversation_when_running_closes_session() -> None:
    conversation_id = "conv-stop-1"
    user_id = "user-1"

    manager = MagicMock()
    manager.get_agent_loop_info = AsyncMock(
        return_value=[SimpleNamespace(status=ConversationStatus.RUNNING)]
    )
    manager.close_session = AsyncMock()

    with patch(
        "backend.api.services.conversation_mutation_service.require_conversation_manager",
        return_value=manager,
    ):
        response = await stop_conversation(
            conversation_id=conversation_id,
            user_id=user_id,
        )

    assert isinstance(response, ConversationResponse)
    assert response.status == "ok"
    assert response.message == "Conversation stopped successfully"
    manager.close_session.assert_awaited_once_with(conversation_id)


@pytest.mark.asyncio
async def test_stop_conversation_when_not_running_is_noop() -> None:
    conversation_id = "conv-stop-2"
    user_id = "user-1"

    manager = MagicMock()
    manager.get_agent_loop_info = AsyncMock(
        return_value=[SimpleNamespace(status=ConversationStatus.STOPPED)]
    )
    manager.close_session = AsyncMock()

    with patch(
        "backend.api.services.conversation_mutation_service.require_conversation_manager",
        return_value=manager,
    ):
        response = await stop_conversation(
            conversation_id=conversation_id,
            user_id=user_id,
        )

    assert isinstance(response, ConversationResponse)
    assert response.status == "ok"
    assert response.message == "Conversation was not running"
    manager.close_session.assert_not_awaited()

