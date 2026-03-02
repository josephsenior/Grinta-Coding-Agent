"""Tests for backend.api.services.conversation_query_service.

Focuses on the pure and near-pure helpers that can be exercised without
a running conversation manager or database:
  - filter_conversations_by_age
  - get_conversation_info
  - search_conversations
  - build_conversation_result_set
  - get_conversation_details
  - delete_conversation_entry
  - resolve_conversation_store
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.core.type_safety.sentinels import MISSING
from backend.api.schemas.conversation_info import ConversationInfo
from backend.api.schemas.conversation_info_result_set import (
    ConversationInfoResultSet,
)
from backend.api.services.conversation_query_service import (
    filter_conversations_by_age,
    get_conversation_info,
    resolve_conversation_store,
    search_conversations,
    build_conversation_result_set,
    get_conversation_details,
    delete_conversation_entry,
)
from backend.storage.data_models.conversation_metadata import (
    ConversationMetadata,
    ConversationTrigger,
)
from backend.storage.data_models.conversation_status import ConversationStatus


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_metadata(
    conversation_id: str = "conv-1",
    title: str = "Test Conversation",
    created_at: datetime | None = None,
    age_seconds: float = 0,
) -> ConversationMetadata:
    """Create a ConversationMetadata with a given age (seconds before now)."""
    if created_at is None:
        created_at = datetime.now(UTC) - timedelta(seconds=age_seconds)
    return ConversationMetadata(
        conversation_id=conversation_id,
        title=title,
        selected_repository=None,
        created_at=created_at,
    )


# ---------------------------------------------------------------------------
# filter_conversations_by_age
# ---------------------------------------------------------------------------


class TestFilterConversationsByAge:
    def test_empty_list_returns_empty(self):
        result = filter_conversations_by_age([], max_age_seconds=3600)
        assert result == []

    def test_young_conversation_is_kept(self):
        young = _make_metadata(age_seconds=100)
        result = filter_conversations_by_age([young], max_age_seconds=3600)
        assert len(result) == 1
        assert result[0] is young

    def test_old_conversation_is_removed(self):
        old = _make_metadata(age_seconds=7200)
        result = filter_conversations_by_age([old], max_age_seconds=3600)
        assert result == []

    def test_conversation_exactly_at_limit_is_kept(self):
        """Age == max_age_seconds means age is NOT strictly greater, so it is kept."""
        exactly = _make_metadata(age_seconds=3600)
        result = filter_conversations_by_age([exactly], max_age_seconds=3600)
        assert len(result) == 1

    def test_conversation_just_under_limit_is_kept(self):
        just_under = _make_metadata(age_seconds=3599)
        result = filter_conversations_by_age([just_under], max_age_seconds=3600)
        assert len(result) == 1

    def test_mixed_ages_only_young_kept(self):
        young1 = _make_metadata("young-1", age_seconds=60)
        young2 = _make_metadata("young-2", age_seconds=1800)
        old1 = _make_metadata("old-1", age_seconds=7200)
        old2 = _make_metadata("old-2", age_seconds=999999)
        result = filter_conversations_by_age(
            [young1, old1, young2, old2], max_age_seconds=3600
        )
        ids = {c.conversation_id for c in result}
        assert ids == {"young-1", "young-2"}

    def test_conversation_without_created_at_attribute_is_skipped(self):
        """Objects missing created_at should not raise and should be filtered."""
        bad_obj = MagicMock(spec=[])  # explicitly no attributes
        result = filter_conversations_by_age([bad_obj], max_age_seconds=3600)
        assert result == []

    def test_zero_max_age_rejects_all_conversations(self):
        convs = [_make_metadata(f"conv-{i}", age_seconds=1) for i in range(5)]
        result = filter_conversations_by_age(convs, max_age_seconds=0)
        assert result == []

    def test_very_large_max_age_keeps_all_conversations(self):
        convs = [_make_metadata(f"conv-{i}", age_seconds=i * 1000) for i in range(5)]
        result = filter_conversations_by_age(convs, max_age_seconds=10_000_000)
        assert len(result) == 5

    def test_order_preserved(self):
        convs = [_make_metadata(f"conv-{i}", age_seconds=i * 10) for i in range(5)]
        result = filter_conversations_by_age(convs, max_age_seconds=3600)
        assert [c.conversation_id for c in result] == [
            c.conversation_id for c in convs
        ]


# ---------------------------------------------------------------------------
# get_conversation_info
# ---------------------------------------------------------------------------


class TestGetConversationInfo:
    """Tests for async get_conversation_info with mocked agent_loop_info."""

    @pytest.mark.asyncio
    async def test_returns_conversation_info_instance(self):
        meta = _make_metadata("abc-123", title="My Chat")
        info = await get_conversation_info(meta, num_connections=0, agent_loop_info=None)
        assert isinstance(info, ConversationInfo)

    @pytest.mark.asyncio
    async def test_conversation_id_matches_metadata(self):
        meta = _make_metadata("abc-123")
        info = await get_conversation_info(meta, num_connections=0, agent_loop_info=None)
        assert info is not None
        assert info.conversation_id == "abc-123"

    @pytest.mark.asyncio
    async def test_title_from_metadata(self):
        meta = _make_metadata(title="Explicit Title")
        info = await get_conversation_info(meta, num_connections=0, agent_loop_info=None)
        assert info is not None
        assert info.title == "Explicit Title"

    @pytest.mark.asyncio
    async def test_empty_title_gets_default_title(self):
        meta = _make_metadata(conversation_id="xyz-456", title="")
        meta.title = ""
        info = await get_conversation_info(meta, num_connections=0, agent_loop_info=None)
        assert info is not None
        # Should be non-empty even without a title
        assert info.title != ""
        assert info.conversation_id in info.title or len(info.title) > 0

    @pytest.mark.asyncio
    async def test_num_connections_is_set(self):
        meta = _make_metadata()
        info = await get_conversation_info(meta, num_connections=3, agent_loop_info=None)
        assert info is not None
        assert info.num_connections == 3

    @pytest.mark.asyncio
    async def test_no_agent_loop_info_gives_stopped_status(self):
        meta = _make_metadata()
        info = await get_conversation_info(meta, num_connections=0, agent_loop_info=None)
        assert info is not None
        assert info.status == ConversationStatus.STOPPED

    @pytest.mark.asyncio
    async def test_no_agent_loop_info_gives_none_url(self):
        meta = _make_metadata()
        info = await get_conversation_info(meta, num_connections=0, agent_loop_info=None)
        assert info is not None
        assert info.url is None

    @pytest.mark.asyncio
    async def test_agent_loop_info_status_is_used(self):
        meta = _make_metadata()
        loop_info = MagicMock()
        loop_info.status = ConversationStatus.RUNNING
        loop_info.runtime_status = None
        loop_info.agent_state = None
        loop_info.url = None
        info = await get_conversation_info(meta, num_connections=1, agent_loop_info=loop_info)
        assert info is not None
        assert info.status == ConversationStatus.RUNNING

    @pytest.mark.asyncio
    async def test_agent_loop_info_url_is_used(self):
        meta = _make_metadata()
        loop_info = MagicMock()
        loop_info.status = ConversationStatus.RUNNING
        loop_info.runtime_status = None
        loop_info.agent_state = None
        loop_info.url = "https://example.com/runtime"
        info = await get_conversation_info(meta, num_connections=1, agent_loop_info=loop_info)
        assert info is not None
        assert info.url == "https://example.com/runtime"

    @pytest.mark.asyncio
    async def test_metadata_fields_propagated(self):
        meta = _make_metadata("conv-42", title="Repo Work")
        meta.selected_repository = "owner/repo"
        meta.selected_branch = "main"
        meta.trigger = ConversationTrigger.GUI
        meta.pr_number = [7, 8]
        info = await get_conversation_info(meta, num_connections=0, agent_loop_info=None)
        assert info is not None
        assert info.selected_repository == "owner/repo"
        assert info.selected_branch == "main"
        assert info.trigger == ConversationTrigger.GUI
        assert info.pr_number == [7, 8]

    @pytest.mark.asyncio
    async def test_exception_in_assembly_returns_none(self):
        """If something fails during assembly, None is returned rather than raising."""
        bad_meta = MagicMock()
        bad_meta.conversation_id = "bad-conv"
        # Raise from a property to trigger the except block inside get_conversation_info
        def _raise_title(self):
            raise RuntimeError("boom")
        type(bad_meta).title = property(_raise_title)
        result = await get_conversation_info(bad_meta, num_connections=0, agent_loop_info=None)
        assert result is None

    @pytest.mark.asyncio
    async def test_created_at_from_metadata(self):
        fixed_time = datetime(2024, 1, 15, 12, 0, 0, tzinfo=UTC)
        meta = _make_metadata(created_at=fixed_time)
        info = await get_conversation_info(meta, num_connections=0, agent_loop_info=None)
        assert info is not None
        assert info.created_at == fixed_time

    @pytest.mark.asyncio
    async def test_last_updated_at_from_metadata(self):
        fixed_time = datetime(2024, 6, 20, 9, 30, 0, tzinfo=UTC)
        meta = _make_metadata()
        meta.last_updated_at = fixed_time
        info = await get_conversation_info(meta, num_connections=0, agent_loop_info=None)
        assert info is not None
        assert info.last_updated_at == fixed_time


# ---------------------------------------------------------------------------
# resolve_conversation_store
# ---------------------------------------------------------------------------


class TestResolveConversationStore:
    @pytest.mark.asyncio
    async def test_returns_provided_store(self):
        mock_store = MagicMock()
        result = await resolve_conversation_store(mock_store)
        assert result is mock_store

    @pytest.mark.asyncio
    async def test_none_with_user_id_calls_get_conversation_store_instance(self):
        with patch("backend.api.services.conversation_query_service.get_conversation_store_instance") as mock_get:
            mock_store = MagicMock()
            mock_get.return_value = mock_store
            
            await resolve_conversation_store(None, user_id="u1")
            
            assert mock_get.called

    @pytest.mark.asyncio
    async def test_none_with_missing_user_id_calls_resolve_store(self):
        with patch("backend.api.utils.resolve_conversation_store") as mock_resolve:
            mock_resolve.return_value = None
            
            await resolve_conversation_store(None, user_id=MISSING)
            
            mock_resolve.assert_called_once()

    @pytest.mark.asyncio
    async def test_none_with_none_user_id_calls_resolve_store(self):
        with patch("backend.api.utils.resolve_conversation_store") as mock_resolve:
            mock_resolve.return_value = None
            
            await resolve_conversation_store(None, user_id=None)
            
            mock_resolve.assert_called_once()


# ---------------------------------------------------------------------------
# search_conversations
# ---------------------------------------------------------------------------


class TestSearchConversations:
    @pytest.mark.asyncio
    async def test_no_store_returns_empty_results(self):
        with patch("backend.api.services.conversation_query_service.resolve_conversation_store") as mock_resolve:
            mock_resolve.return_value = None
            
            result = await search_conversations()
            
            assert isinstance(result, ConversationInfoResultSet)
            assert result.results == []
            assert result.next_page_id is None

    @pytest.mark.asyncio
    async def test_search_with_pagination(self):
        meta = _make_metadata("c1", title="Test")
        mock_store = MagicMock()
        result_set = MagicMock()
        result_set.results = [meta]
        result_set.next_page_id = "page-2"
        mock_store.search = AsyncMock(return_value=result_set)
        
        with patch("backend.api.services.conversation_query_service.resolve_conversation_store") as mock_resolve:
            mock_resolve.return_value = mock_store
            
            with patch("backend.api.services.conversation_query_service.build_conversation_result_set") as mock_build:
                mock_build.return_value = ConversationInfoResultSet(results=[], next_page_id="page-2")
                
                await search_conversations(page_id="page-1", limit=50)
                
                assert mock_store.search.called

    @pytest.mark.asyncio
    async def test_search_with_repository_filter(self):
        meta = _make_metadata("c1")
        meta.selected_repository = "repo1"
        mock_store = MagicMock()
        result_set = MagicMock()
        result_set.results = [meta]
        result_set.next_page_id = None
        mock_store.search = AsyncMock(return_value=result_set)
        
        with patch("backend.api.services.conversation_query_service.resolve_conversation_store") as mock_resolve:
            mock_resolve.return_value = mock_store
            
            with patch("backend.api.services.conversation_query_service.build_conversation_result_set") as mock_build:
                mock_build.return_value = ConversationInfoResultSet(results=[], next_page_id=None)
                
                await search_conversations(selected_repository="repo1")
                
                assert mock_build.called


# ---------------------------------------------------------------------------
# build_conversation_result_set
# ---------------------------------------------------------------------------


class TestBuildConversationResultSet:
    @pytest.mark.asyncio
    async def test_builds_result_set_from_conversations(self):
        meta = _make_metadata("c1")
        
        with patch("backend.api.services.conversation_query_service._require_conversation_manager") as mock_req:
            mock_mgr = MagicMock()
            mock_mgr.get_connections = AsyncMock(return_value={})
            mock_mgr.get_agent_loop_info = AsyncMock(return_value=[])
            mock_req.return_value = mock_mgr
            
            with patch("backend.api.services.conversation_query_service.wait_all") as mock_wait:
                mock_wait.return_value = [MagicMock(conversation_id="c1")]
                
                result = await build_conversation_result_set([meta], None)
                
                assert isinstance(result, ConversationInfoResultSet)
                assert result.next_page_id is None


# ---------------------------------------------------------------------------
# get_conversation_details
# ---------------------------------------------------------------------------


class TestGetConversationDetails:
    @pytest.mark.asyncio
    async def test_returns_none_if_not_found(self):
        mock_store = MagicMock()
        mock_store.get_metadata = AsyncMock(side_effect=FileNotFoundError)
        
        with patch("backend.api.services.conversation_query_service.resolve_conversation_store") as mock_resolve:
            mock_resolve.return_value = mock_store
            
            result = await get_conversation_details("c1")
            
            assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_if_no_store(self):
        with patch("backend.api.services.conversation_query_service.resolve_conversation_store") as mock_resolve:
            mock_resolve.return_value = None
            
            result = await get_conversation_details("c1")
            
            assert result is None

    @pytest.mark.asyncio
    async def test_gets_details_with_agent_loop_info(self):
        meta = _make_metadata("c1")
        mock_store = MagicMock()
        mock_store.get_metadata = AsyncMock(return_value=meta)
        
        with patch("backend.api.services.conversation_query_service.resolve_conversation_store") as mock_resolve:
            mock_resolve.return_value = mock_store
            
            with patch("backend.api.services.conversation_query_service._require_conversation_manager") as mock_req:
                mock_mgr = MagicMock()
                loop_info = MagicMock()
                loop_info.conversation_id = "c1"
                mock_mgr.get_agent_loop_info = AsyncMock(return_value=[loop_info])
                mock_mgr.get_connections = AsyncMock(return_value=None)
                mock_req.return_value = mock_mgr
                
                with patch("backend.api.services.conversation_query_service.get_conversation_info") as mock_info:
                    mock_info.return_value = MagicMock()
                    
                    result = await get_conversation_details("c1")
                    
                    assert result is not None


# ---------------------------------------------------------------------------
# delete_conversation_entry
# ---------------------------------------------------------------------------


class TestDeleteConversationEntry:
    @pytest.mark.asyncio
    async def test_returns_false_if_no_store(self):
        with patch("backend.api.services.conversation_query_service.resolve_conversation_store") as mock_resolve:
            mock_resolve.return_value = None
            
            result = await delete_conversation_entry("c1")
            
            assert result is False

    @pytest.mark.asyncio
    async def test_returns_false_if_not_found(self):
        mock_store = MagicMock()
        mock_store.get_metadata = AsyncMock(side_effect=FileNotFoundError)
        
        with patch("backend.api.services.conversation_query_service.resolve_conversation_store") as mock_resolve:
            mock_resolve.return_value = mock_store
            
            result = await delete_conversation_entry("c1")
            
            assert result is False

    @pytest.mark.asyncio
    async def test_deletes_metadata_and_runtime(self):
        meta = _make_metadata("c1")
        mock_store = MagicMock()
        mock_store.get_metadata = AsyncMock(return_value=meta)
        mock_store.delete_metadata = AsyncMock()
        
        with patch("backend.api.services.conversation_query_service.resolve_conversation_store") as mock_resolve:
            mock_resolve.return_value = mock_store
            
            with patch("backend.api.services.conversation_query_service._require_conversation_manager") as mock_req:
                mock_mgr = MagicMock()
                mock_mgr.is_agent_loop_running = AsyncMock(return_value=False)
                mock_mgr.close_session = AsyncMock()
                mock_req.return_value = mock_mgr
                
                with patch("backend.api.services.conversation_query_service.get_runtime_cls") as mock_runtime:
                    mock_rt = MagicMock()
                    mock_rt.delete = AsyncMock()
                    mock_runtime.return_value = mock_rt
                    
                    result = await delete_conversation_entry("c1")
                    
                    assert result is True
                    mock_store.delete_metadata.assert_called_once()
                    mock_rt.delete.assert_called_once()

    @pytest.mark.asyncio
    async def test_closes_agent_loop_if_running(self):
        meta = _make_metadata("c1")
        mock_store = MagicMock()
        mock_store.get_metadata = AsyncMock(return_value=meta)
        mock_store.delete_metadata = AsyncMock()
        
        with patch("backend.api.services.conversation_query_service.resolve_conversation_store") as mock_resolve:
            mock_resolve.return_value = mock_store
            
            with patch("backend.api.services.conversation_query_service._require_conversation_manager") as mock_req:
                mock_mgr = MagicMock()
                mock_mgr.is_agent_loop_running = AsyncMock(return_value=True)
                mock_mgr.close_session = AsyncMock()
                mock_req.return_value = mock_mgr
                
                with patch("backend.api.services.conversation_query_service.get_runtime_cls") as mock_runtime:
                    mock_rt = MagicMock()
                    mock_rt.delete = AsyncMock()
                    mock_runtime.return_value = mock_rt
                    
                    await delete_conversation_entry("c1")
                    
                    mock_mgr.close_session.assert_called_once_with("c1")
