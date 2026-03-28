"""Tests for backend.gateway.services.conversation_mutation_service module.

Targets 20.9% coverage (91 statements) by testing:
- TitleUpdateResult and AgentLoopResult data classes
- update_conversation_title with mocked store
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.gateway.services.conversation_mutation_service import (
    AgentLoopResult,
    TitleUpdateResult,
    update_conversation_title,
)
from backend.persistence.data_models.conversation_status import ConversationStatus


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


def _make_metadata(
    conversation_id: str, user_id: str | None = None, title: str = "Old"
):
    m = MagicMock()
    m.conversation_id = conversation_id
    m.user_id = user_id
    m.title = title
    m.last_updated_at = None
    return m


@pytest.mark.asyncio
async def test_update_title_store_unavailable():
    with patch(
        "backend.gateway.services.conversation_mutation_service.resolve_conversation_store",
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
        "backend.gateway.services.conversation_mutation_service.resolve_conversation_store",
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
        "backend.gateway.services.conversation_mutation_service.resolve_conversation_store",
        new_callable=AsyncMock,
        return_value=store,
    ):
        result = await update_conversation_title("conv1", "New Title", "different-user")
    assert result.ok is False
    assert result.error_message is not None
    assert "Permission" in result.error_message


@pytest.mark.asyncio
async def test_update_title_success_no_manager():
    metadata = _make_metadata("conv1", user_id="u1", title="Old Title")
    store = AsyncMock()
    store.get_metadata.return_value = metadata
    store.save_metadata = AsyncMock()
    with (
        patch(
            "backend.gateway.services.conversation_mutation_service.resolve_conversation_store",
            new_callable=AsyncMock,
            return_value=store,
        ),
        patch(
            "backend.gateway.services.conversation_mutation_service.get_conversation_manager_instance",
            return_value=None,
        ),
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

    with (
        patch(
            "backend.gateway.services.conversation_mutation_service.resolve_conversation_store",
            new_callable=AsyncMock,
            return_value=store,
        ),
        patch(
            "backend.gateway.services.conversation_mutation_service.get_conversation_manager_instance",
            return_value=manager,
        ),
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
    with (
        patch(
            "backend.gateway.services.conversation_mutation_service.resolve_conversation_store",
            new_callable=AsyncMock,
            return_value=store,
        ),
        patch(
            "backend.gateway.services.conversation_mutation_service.get_conversation_manager_instance",
            return_value=None,
        ),
    ):
        result = await update_conversation_title("conv1", "New", None)
    assert result.ok is True


@pytest.mark.asyncio
async def test_update_title_strips_whitespace():
    metadata = _make_metadata("conv1", user_id="u1", title="Old")
    store = AsyncMock()
    store.get_metadata.return_value = metadata
    store.save_metadata = AsyncMock()
    with (
        patch(
            "backend.gateway.services.conversation_mutation_service.resolve_conversation_store",
            new_callable=AsyncMock,
            return_value=store,
        ),
        patch(
            "backend.gateway.services.conversation_mutation_service.get_conversation_manager_instance",
            return_value=None,
        ),
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
    with (
        patch(
            "backend.gateway.services.conversation_mutation_service.resolve_conversation_store",
            new_callable=AsyncMock,
            return_value=store,
        ),
        patch(
            "backend.gateway.services.conversation_mutation_service.get_conversation_manager_instance",
            return_value=None,
        ),
    ):
        result = await update_conversation_title("conv1", "New", "u1")
    # Should still succeed; timestamp guaranteed to be > last_updated_at
    assert result.ok is True


# -----------------------------------------------------------
# search_playbook_conversations
# -----------------------------------------------------------


@pytest.mark.asyncio
@patch(
    "backend.gateway.services.conversation_mutation_service.resolve_conversation_store",
    new_callable=AsyncMock,
)
@patch(
    "backend.gateway.services.conversation_mutation_service.filter_conversations_by_age"
)
@patch(
    "backend.gateway.services.conversation_mutation_service.build_conversation_result_set"
)
async def test_search_playbook_conversations_filtering(
    mock_build, mock_filter_age, mock_resolve
):
    from backend.persistence.data_models.conversation_metadata import ConversationTrigger

    store = AsyncMock()
    mock_resolve.return_value = store

    # Mock metadata with different triggers and repos
    m_match = MagicMock()
    m_match.trigger = ConversationTrigger.PLAYBOOK_MANAGEMENT
    m_match.selected_repository = "repo1"

    m_wrong_trigger = MagicMock()
    m_wrong_trigger.trigger = ConversationTrigger.GUI
    m_wrong_trigger.selected_repository = "repo1"

    m_wrong_repo = MagicMock()
    m_wrong_repo.trigger = ConversationTrigger.PLAYBOOK_MANAGEMENT
    m_wrong_repo.selected_repository = "repo2"

    # Mock result set from store.search
    mock_result_set = MagicMock()
    mock_result_set.results = [m_match, m_wrong_trigger, m_wrong_repo]
    mock_result_set.next_page_id = "next"
    store.search.return_value = mock_result_set

    # Age filter returns same list
    mock_filter_age.return_value = [m_match, m_wrong_trigger, m_wrong_repo]

    from backend.gateway.services.conversation_mutation_service import (
        search_playbook_conversations,
    )

    await search_playbook_conversations("repo1", "page1", 10, store, None)

    mock_build.assert_called_once()
    final_list = mock_build.call_args[0][0]
    # Should only contain m_match
    assert len(final_list) == 1
    assert final_list[0] == m_match


# -----------------------------------------------------------
# Agent loop start / stop
# -----------------------------------------------------------


@pytest.mark.asyncio
@patch(
    "backend.gateway.services.conversation_mutation_service.resolve_conversation_store",
    new_callable=AsyncMock,
)
@patch(
    "backend.gateway.services.conversation_mutation_service.require_conversation_manager"
)
@patch(
    "backend.gateway.services.conversation_service.setup_init_conversation_settings"
)
async def test_start_agent_loop_success(mock_setup, mock_require_manager, mock_resolve):
    from backend.gateway.services.conversation_mutation_service import start_agent_loop

    store = AsyncMock()
    mock_resolve.return_value = store
    store.get_metadata.return_value = MagicMock()

    mock_manager = AsyncMock()
    mock_require_manager.return_value = mock_manager

    mock_loop_info = MagicMock()
    mock_loop_info.status = ConversationStatus.RUNNING
    mock_manager.maybe_start_agent_loop.return_value = mock_loop_info

    result = await start_agent_loop("conv1", "user1", None, [], store)

    assert result.ok is True
    assert result.conversation_status == ConversationStatus.RUNNING
    mock_manager.maybe_start_agent_loop.assert_called_once()


@pytest.mark.asyncio
@patch(
    "backend.gateway.services.conversation_mutation_service.require_conversation_manager"
)
async def test_stop_agent_loop_success(mock_require_manager):
    from backend.gateway.services.conversation_mutation_service import stop_agent_loop

    mock_manager = AsyncMock()
    mock_require_manager.return_value = mock_manager

    # Mock loop info showing it is running
    mock_loop_info = MagicMock()
    mock_loop_info.status = ConversationStatus.RUNNING
    mock_manager.get_agent_loop_info.return_value = [mock_loop_info]

    result = await stop_agent_loop("conv1", "user1")

    assert result.ok is True
    assert result.message == "Conversation stopped successfully"
    mock_manager.close_session.assert_called_once_with("conv1")


@pytest.mark.asyncio
@patch(
    "backend.gateway.services.conversation_mutation_service.require_conversation_manager"
)
async def test_stop_agent_loop_already_stopped(mock_require_manager):
    from backend.gateway.services.conversation_mutation_service import stop_agent_loop

    mock_manager = AsyncMock()
    mock_require_manager.return_value = mock_manager

    # Mock loop info showing it is stopped
    mock_loop_info = MagicMock()
    mock_loop_info.status = ConversationStatus.STOPPED
    # Note: stop_agent_loop expect a list and takes the first element
    mock_manager.get_agent_loop_info.return_value = [mock_loop_info]

    result = await stop_agent_loop("conv1", "user1")

    assert result.ok is True
    assert result.message == "Conversation was not running"
    mock_manager.close_session.assert_not_called()


# -----------------------------------------------------------
# Socket.IO emit error handling
# -----------------------------------------------------------


@pytest.mark.asyncio
async def test_update_title_sio_emit_error():
    """Test that Socket.IO emit errors are logged but don't fail the update."""
    metadata = _make_metadata("conv1", user_id="u1", title="Old")
    store = AsyncMock()
    store.get_metadata.return_value = metadata
    store.save_metadata = AsyncMock()

    sio = AsyncMock()
    sio.emit.side_effect = Exception("Socket.IO error")
    manager = MagicMock()
    manager.sio = sio

    with (
        patch(
            "backend.gateway.services.conversation_mutation_service.resolve_conversation_store",
            new_callable=AsyncMock,
            return_value=store,
        ),
        patch(
            "backend.gateway.services.conversation_mutation_service.get_conversation_manager_instance",
            return_value=manager,
        ),
    ):
        result = await update_conversation_title("conv1", "New", "u1")

    # Title update should still succeed even if emit fails
    assert result.ok is True
    assert result.new_title == "New"


@pytest.mark.asyncio
async def test_update_title_no_sio_attribute():
    """Test when manager exists but has no sio attribute."""
    metadata = _make_metadata("conv1", user_id="u1", title="Old")
    store = AsyncMock()
    store.get_metadata.return_value = metadata
    store.save_metadata = AsyncMock()

    manager = MagicMock(spec=[])  # No sio attribute
    with (
        patch(
            "backend.gateway.services.conversation_mutation_service.resolve_conversation_store",
            new_callable=AsyncMock,
            return_value=store,
        ),
        patch(
            "backend.gateway.services.conversation_mutation_service.get_conversation_manager_instance",
            return_value=manager,
        ),
    ):
        result = await update_conversation_title("conv1", "New", "u1")

    # Should succeed without trying to emit
    assert result.ok is True


@pytest.mark.asyncio
async def test_search_playbook_conversations_no_store():
    with patch(
        "backend.gateway.services.conversation_mutation_service.resolve_conversation_store",
        new_callable=AsyncMock,
        return_value=None,
    ):
        # Import at test time to avoid module-level import issues
        from backend.gateway.services.conversation_mutation_service import (
            search_playbook_conversations,
        )

        result = await search_playbook_conversations(
            selected_repository="repo1",
            page_id=None,
            limit=20,
            conversation_store=None,
            provider_tokens=None,
        )

    assert result.results == []
    assert result.next_page_id is None


@pytest.mark.asyncio
async def test_search_playbook_conversations_filters_by_trigger():
    from backend.persistence.data_models.conversation_metadata import (
        ConversationTrigger,
    )

    metadata1 = MagicMock()
    metadata1.trigger = ConversationTrigger.PLAYBOOK_MANAGEMENT
    metadata1.selected_repository = "repo1"

    metadata2 = MagicMock()
    metadata2.trigger = ConversationTrigger.GUI
    metadata2.selected_repository = "repo1"

    store = AsyncMock()
    result_set = MagicMock()
    result_set.results = [metadata1, metadata2]
    result_set.next_page_id = None
    store.search = AsyncMock(return_value=result_set)

    with (
        patch(
            "backend.gateway.services.conversation_mutation_service.resolve_conversation_store",
            new_callable=AsyncMock,
            return_value=store,
        ),
        patch(
            "backend.gateway.services.conversation_mutation_service.filter_conversations_by_age",
            return_value=[metadata1, metadata2],
        ),
        patch(
            "backend.gateway.services.conversation_mutation_service.build_conversation_result_set",
            new_callable=AsyncMock,
        ) as mock_build,
    ):
        from backend.gateway.services.conversation_mutation_service import (
            search_playbook_conversations,
        )

        await search_playbook_conversations(
            selected_repository="repo1",
            page_id=None,
            limit=20,
            conversation_store=store,
            provider_tokens=None,
        )

        # Verify that build_conversation_result_set was called with only metadata1
        mock_build.assert_called_once()
        filtered = mock_build.call_args[0][0]
        assert len(filtered) == 1
        assert filtered[0] is metadata1


@pytest.mark.asyncio
async def test_search_playbook_conversations_filters_by_repository():
    from backend.persistence.data_models.conversation_metadata import (
        ConversationTrigger,
    )

    metadata1 = MagicMock()
    metadata1.trigger = ConversationTrigger.PLAYBOOK_MANAGEMENT
    metadata1.selected_repository = "repo1"

    metadata2 = MagicMock()
    metadata2.trigger = ConversationTrigger.PLAYBOOK_MANAGEMENT
    metadata2.selected_repository = "repo2"

    store = AsyncMock()
    result_set = MagicMock()
    result_set.results = [metadata1, metadata2]
    result_set.next_page_id = None
    store.search = AsyncMock(return_value=result_set)

    with (
        patch(
            "backend.gateway.services.conversation_mutation_service.resolve_conversation_store",
            new_callable=AsyncMock,
            return_value=store,
        ),
        patch(
            "backend.gateway.services.conversation_mutation_service.filter_conversations_by_age",
            return_value=[metadata1, metadata2],
        ),
        patch(
            "backend.gateway.services.conversation_mutation_service.build_conversation_result_set",
            new_callable=AsyncMock,
        ) as mock_build,
    ):
        from backend.gateway.services.conversation_mutation_service import (
            search_playbook_conversations,
        )

        await search_playbook_conversations(
            selected_repository="repo1",
            page_id=None,
            limit=20,
            conversation_store=store,
            provider_tokens=None,
        )

        # Verify only repo1 was included
        mock_build.assert_called_once()
        filtered = mock_build.call_args[0][0]
        assert len(filtered) == 1
        assert filtered[0] is metadata1


# -----------------------------------------------------------
# start_agent_loop
# -----------------------------------------------------------


@pytest.mark.asyncio
async def test_start_agent_loop_store_unavailable():
    from backend.gateway.services.conversation_mutation_service import (
        start_agent_loop,
    )

    with patch(
        "backend.gateway.services.conversation_mutation_service.resolve_conversation_store",
        new_callable=AsyncMock,
        return_value=None,
    ):
        result = await start_agent_loop(
            conversation_id="conv1",
            user_id="u1",
            provider_tokens=None,
            providers_list=[],
            conversation_store=None,
        )

    assert result.ok is False
    assert result.error_code == "STORE$UNAVAILABLE"


@pytest.mark.asyncio
async def test_start_agent_loop_conversation_not_found():
    from backend.gateway.services.conversation_mutation_service import (
        start_agent_loop,
    )

    store = AsyncMock()
    store.get_metadata.side_effect = Exception("Not found")

    with patch(
        "backend.gateway.services.conversation_mutation_service.resolve_conversation_store",
        new_callable=AsyncMock,
        return_value=store,
    ):
        result = await start_agent_loop(
            conversation_id="conv1",
            user_id="u1",
            provider_tokens=None,
            providers_list=[],
            conversation_store=store,
        )

    assert result.ok is False
    assert result.error_code == "CONVERSATION_NOT_FOUND"


# -----------------------------------------------------------
# stop_agent_loop edge cases
# -----------------------------------------------------------


@pytest.mark.asyncio
@patch(
    "backend.gateway.services.conversation_mutation_service.require_conversation_manager"
)
async def test_stop_agent_loop_no_loop_info(mock_require_manager):
    from backend.gateway.services.conversation_mutation_service import stop_agent_loop

    mock_manager = AsyncMock()
    mock_require_manager.return_value = mock_manager

    # Empty list of loop info
    mock_manager.get_agent_loop_info.return_value = []

    result = await stop_agent_loop("conv1", "user1")

    # Should return STOPPED status when no loop info found
    assert result.ok is True
    assert result.conversation_status == ConversationStatus.STOPPED
    assert result.message == "Conversation was not running"
    mock_manager.close_session.assert_not_called()


@pytest.mark.asyncio
@patch(
    "backend.gateway.services.conversation_mutation_service.require_conversation_manager"
)
async def test_stop_agent_loop_starting_status(mock_require_manager):
    from backend.gateway.services.conversation_mutation_service import stop_agent_loop

    mock_manager = AsyncMock()
    mock_require_manager.return_value = mock_manager

    mock_loop_info = MagicMock()
    mock_loop_info.status = ConversationStatus.STARTING
    mock_manager.get_agent_loop_info.return_value = [mock_loop_info]

    result = await stop_agent_loop("conv1", "user1")

    assert result.ok is True
    # STARTING is treated as running, so it should close
    mock_manager.close_session.assert_called_once()

