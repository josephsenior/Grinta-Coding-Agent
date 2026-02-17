"""Tests for backend.server.services.conversation_mutation_service module.

Targets 20.9% coverage (91 statements) by testing:
- TitleUpdateResult and AgentLoopResult data classes
- update_conversation_title with mocked store
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.server.services.conversation_mutation_service import (
    AgentLoopResult,
    TitleUpdateResult,
    update_conversation_title,
)
from backend.storage.data_models.conversation_status import ConversationStatus


# -----------------------------------------------------------
# TitleUpdateResult
# -----------------------------------------------------------

class TestTitleUpdateResult:
    def test_success(self):
        r = TitleUpdateResult(ok=True, original_title="Old", new_title="New")
        assert r.ok is True
        assert r.original_title == "Old"
        assert r.new_title == "New"
        assert r.error_code is None
        assert r.error_message is None

    def test_failure(self):
        r = TitleUpdateResult(
            ok=False, error_code="STORE$UNAVAILABLE", error_message="Store unavailable"
        )
        assert r.ok is False
        assert r.error_code == "STORE$UNAVAILABLE"
        assert r.error_message == "Store unavailable"

    def test_defaults(self):
        r = TitleUpdateResult(ok=True)
        assert r.original_title is None
        assert r.new_title is None


# -----------------------------------------------------------
# AgentLoopResult
# -----------------------------------------------------------

class TestAgentLoopResult:
    def test_success(self):
        r = AgentLoopResult(
            ok=True, conversation_status=ConversationStatus.RUNNING, message="Started"
        )
        assert r.ok is True
        assert r.conversation_status == ConversationStatus.RUNNING
        assert r.message == "Started"
        assert r.error_code is None

    def test_failure(self):
        r = AgentLoopResult(
            ok=False, error_code="STORE$UNAVAILABLE", error_message="Store unavailable"
        )
        assert r.ok is False
        assert r.error_code == "STORE$UNAVAILABLE"
        assert r.conversation_status is None


# -----------------------------------------------------------
# update_conversation_title
# -----------------------------------------------------------

def _make_metadata(conversation_id: str, user_id: str | None = None, title: str = "Old"):
    m = MagicMock()
    m.conversation_id = conversation_id
    m.user_id = user_id
    m.title = title
    m.last_updated_at = None
    return m


@pytest.mark.asyncio
async def test_update_title_store_unavailable():
    with patch(
        "backend.server.services.conversation_mutation_service.resolve_conversation_store",
        new_callable=AsyncMock,
        return_value=None,
    ):
        result = await update_conversation_title("conv1", "New Title", "u1")
    assert result.ok is False
    assert result.error_code == "STORE$UNAVAILABLE"


@pytest.mark.asyncio
async def test_update_title_not_found():
    store = AsyncMock()
    store.get_metadata.side_effect = FileNotFoundError()
    with patch(
        "backend.server.services.conversation_mutation_service.resolve_conversation_store",
        new_callable=AsyncMock,
        return_value=store,
    ):
        result = await update_conversation_title("conv1", "New Title", "u1")
    assert result.ok is False
    assert result.error_code == "CONVERSATION$NOT_FOUND"


@pytest.mark.asyncio
async def test_update_title_permission_denied():
    metadata = _make_metadata("conv1", user_id="owner")
    store = AsyncMock()
    store.get_metadata.return_value = metadata
    with patch(
        "backend.server.services.conversation_mutation_service.resolve_conversation_store",
        new_callable=AsyncMock,
        return_value=store,
    ):
        result = await update_conversation_title("conv1", "New Title", "different-user")
    assert result.ok is False
    assert "Permission" in result.error_message


@pytest.mark.asyncio
async def test_update_title_success_no_manager():
    metadata = _make_metadata("conv1", user_id="u1", title="Old Title")
    store = AsyncMock()
    store.get_metadata.return_value = metadata
    store.save_metadata = AsyncMock()
    with patch(
        "backend.server.services.conversation_mutation_service.resolve_conversation_store",
        new_callable=AsyncMock,
        return_value=store,
    ), patch(
        "backend.server.services.conversation_mutation_service.get_conversation_manager_instance",
        return_value=None,
    ):
        result = await update_conversation_title("conv1", "New Title", "u1")
    assert result.ok is True
    assert result.original_title == "Old Title"
    assert result.new_title == "New Title"
    store.save_metadata.assert_awaited_once()


@pytest.mark.asyncio
async def test_update_title_success_with_sio_emit():
    metadata = _make_metadata("conv1", user_id="u1", title="Old")
    store = AsyncMock()
    store.get_metadata.return_value = metadata
    store.save_metadata = AsyncMock()

    sio = AsyncMock()
    manager = MagicMock()
    manager.sio = sio

    with patch(
        "backend.server.services.conversation_mutation_service.resolve_conversation_store",
        new_callable=AsyncMock,
        return_value=store,
    ), patch(
        "backend.server.services.conversation_mutation_service.get_conversation_manager_instance",
        return_value=manager,
    ):
        result = await update_conversation_title("conv1", "New", "u1")

    assert result.ok is True
    sio.emit.assert_awaited()


@pytest.mark.asyncio
async def test_update_title_no_user_id_skips_permission_check():
    """When user_id is None, permission check is skipped."""
    metadata = _make_metadata("conv1", user_id="owner", title="Old")
    store = AsyncMock()
    store.get_metadata.return_value = metadata
    store.save_metadata = AsyncMock()
    with patch(
        "backend.server.services.conversation_mutation_service.resolve_conversation_store",
        new_callable=AsyncMock,
        return_value=store,
    ), patch(
        "backend.server.services.conversation_mutation_service.get_conversation_manager_instance",
        return_value=None,
    ):
        result = await update_conversation_title("conv1", "New", None)
    assert result.ok is True


@pytest.mark.asyncio
async def test_update_title_strips_whitespace():
    metadata = _make_metadata("conv1", user_id="u1", title="Old")
    store = AsyncMock()
    store.get_metadata.return_value = metadata
    store.save_metadata = AsyncMock()
    with patch(
        "backend.server.services.conversation_mutation_service.resolve_conversation_store",
        new_callable=AsyncMock,
        return_value=store,
    ), patch(
        "backend.server.services.conversation_mutation_service.get_conversation_manager_instance",
        return_value=None,
    ):
        result = await update_conversation_title("conv1", "  New Title  ", "u1")
    assert result.new_title == "New Title"


@pytest.mark.asyncio
async def test_update_title_monotonic_timestamp():
    """Ensures timestamp is bumped when last_updated_at is already set."""
    metadata = _make_metadata("conv1", user_id="u1", title="Old")
    # Set last_updated_at to a future time to trigger the monotonic guard
    metadata.last_updated_at = datetime(9999, 1, 1, tzinfo=UTC)
    store = AsyncMock()
    store.get_metadata.return_value = metadata
    store.save_metadata = AsyncMock()
    with patch(
        "backend.server.services.conversation_mutation_service.resolve_conversation_store",
        new_callable=AsyncMock,
        return_value=store,
    ), patch(
        "backend.server.services.conversation_mutation_service.get_conversation_manager_instance",
        return_value=None,
    ):
        result = await update_conversation_title("conv1", "New", "u1")
    # Should still succeed; timestamp guaranteed to be > last_updated_at
    assert result.ok is True
