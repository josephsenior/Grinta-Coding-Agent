"""Conversation query and lifecycle operations.

Extracted from ``conversation_collection.py`` to keep route handlers thin.
Contains filtering, search, detail retrieval, deletion, and info assembly.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from backend.core.logger import forge_logger as logger
from backend.core.type_safety.sentinels import MISSING, Sentinel, is_missing
from backend.runtime import get_runtime_cls
from backend.api.schemas.conversation_info import ConversationInfo
from backend.api.schemas.conversation_info_result_set import (
    ConversationInfoResultSet,
)
from backend.api.services.service_dependencies import (
    require_conversation_manager as _require_conversation_manager,
)
from backend.api.app_accessors import ConversationStoreImpl, config
from backend.api.store_factory import get_conversation_store_instance
from backend.storage.conversation.conversation_store import ConversationStore
from backend.storage.data_models.conversation_metadata import (
    ConversationMetadata,
    ConversationTrigger,
)
from backend.storage.data_models.conversation_status import ConversationStatus
from backend.utils.async_utils import wait_all
from backend.utils.conversation_summary import get_default_conversation_title

if TYPE_CHECKING:
    from backend.api.schemas.agent_loop_info import AgentLoopInfo


# ---------------------------------------------------------------------------
# Store resolution
# ---------------------------------------------------------------------------


async def resolve_conversation_store(
    conversation_store: ConversationStore | None,
    user_id: str | None | Sentinel = MISSING,
) -> ConversationStore | None:
    """Resolve conversation store, delegating to shared utilities."""
    if conversation_store is not None:
        return conversation_store
    from backend.api.utils import resolve_conversation_store as _resolve_store

    if not is_missing(user_id) and user_id is not None:
        return await get_conversation_store_instance(
            ConversationStoreImpl, config, str(user_id)
        )
    return await _resolve_store(None)


# ---------------------------------------------------------------------------
# Filtering helpers
# ---------------------------------------------------------------------------


def _apply_search_filters(
    conversations: list[ConversationMetadata],
    *,
    selected_repository: str | None | Sentinel = MISSING,
    conversation_trigger: ConversationTrigger | None | Sentinel = MISSING,
) -> list[ConversationMetadata]:
    """Apply repository and trigger filters to conversations."""
    result: list[ConversationMetadata] = []
    for conv in conversations:
        if (
            not is_missing(selected_repository)
            and selected_repository is not None
            and conv.selected_repository != selected_repository
        ):
            continue
        if (
            not is_missing(conversation_trigger)
            and conversation_trigger is not None
            and conv.trigger != conversation_trigger
        ):
            continue
        result.append(conv)
    return result


def filter_conversations_by_age(
    conversations: list[ConversationMetadata], max_age_seconds: int
) -> list[ConversationMetadata]:
    """Filter conversations by age, removing those older than *max_age_seconds*."""
    now = datetime.now(UTC)
    filtered_results: list[ConversationMetadata] = []
    for conversation in conversations:
        if not hasattr(conversation, "created_at"):
            continue
        age_seconds = (
            now - conversation.created_at.replace(tzinfo=UTC)
        ).total_seconds()
        if age_seconds > max_age_seconds:
            continue
        filtered_results.append(conversation)
    return filtered_results


# ---------------------------------------------------------------------------
# Info assembly
# ---------------------------------------------------------------------------


async def get_conversation_info(
    conversation: ConversationMetadata,
    num_connections: int,
    agent_loop_info: AgentLoopInfo | None,
) -> ConversationInfo | None:
    """Build a ``ConversationInfo`` from metadata + runtime state."""
    try:
        title = conversation.title or get_default_conversation_title(
            conversation.conversation_id
        )
        return ConversationInfo(
            trigger=conversation.trigger,
            conversation_id=conversation.conversation_id,
            title=title,
            last_updated_at=conversation.last_updated_at,
            created_at=conversation.created_at,
            selected_repository=conversation.selected_repository,
            selected_branch=conversation.selected_branch,
            vcs_provider=conversation.vcs_provider,
            status=getattr(agent_loop_info, "status", ConversationStatus.STOPPED),
            runtime_status=getattr(agent_loop_info, "runtime_status", None),
            agent_state=getattr(agent_loop_info, "agent_state", None),
            num_connections=num_connections,
            url=agent_loop_info.url if agent_loop_info else None,
            pr_number=conversation.pr_number,
        )
    except Exception as e:
        logger.error(
            "Error loading conversation %s: %s",
            conversation.conversation_id,
            str(e),
            extra={"session_id": conversation.conversation_id},
        )
        return None


async def build_conversation_result_set(
    filtered_conversations: list[ConversationMetadata],
    next_page_id: str | None,
) -> ConversationInfoResultSet:
    """Build a ``ConversationInfoResultSet`` from filtered conversations."""
    manager = _require_conversation_manager()
    conversation_ids = {
        conversation.conversation_id for conversation in filtered_conversations
    }
    connection_ids_to_conversation_ids = await manager.get_connections(
        filter_to_sids=conversation_ids
    )
    agent_loop_info_list = await manager.get_agent_loop_info(
        filter_to_sids=conversation_ids
    )
    agent_loop_info_by_conversation_id = {
        info.conversation_id: info for info in agent_loop_info_list
    }
    return ConversationInfoResultSet(
        results=await wait_all(
            get_conversation_info(
                conversation=conversation,
                num_connections=sum(
                    cid == conversation.conversation_id
                    for cid in connection_ids_to_conversation_ids.values()
                ),
                agent_loop_info=agent_loop_info_by_conversation_id.get(
                    conversation.conversation_id
                ),
            )
            for conversation in filtered_conversations
        ),
        next_page_id=next_page_id,
    )


# ---------------------------------------------------------------------------
# Search / list
# ---------------------------------------------------------------------------


async def search_conversations(
    *,
    page_id: str | None | Sentinel = MISSING,
    limit: int = 20,
    conversation_store: Any | None = None,
    user_id: str | None | Sentinel = MISSING,
    selected_repository: str | None | Sentinel = MISSING,
    conversation_trigger: ConversationTrigger | None | Sentinel = MISSING,
) -> ConversationInfoResultSet:
    """Search and filter conversations with pagination."""
    logger.info(
        "search_conversations called with: page_id=%s, limit=%s, user_id=%s, selected_repository=%s, conversation_trigger=%s",
        page_id,
        limit,
        user_id,
        selected_repository,
        conversation_trigger,
    )
    store = await resolve_conversation_store(conversation_store, user_id)
    if store is None:
        return ConversationInfoResultSet(results=[], next_page_id=None)

    search_page_id: str | None = (
        None if is_missing(page_id) else (None if page_id is None else str(page_id))
    )
    conversation_metadata_result_set = await store.search(search_page_id, limit)
    logger.info(
        "conversation_store.search returned %d conversations",
        len(conversation_metadata_result_set.results),
    )
    filtered_results = filter_conversations_by_age(
        conversation_metadata_result_set.results,
        config.conversation_max_age_seconds,
    )
    final_filtered_results = _apply_search_filters(
        filtered_results,
        selected_repository=selected_repository,
        conversation_trigger=conversation_trigger,
    )
    return await build_conversation_result_set(
        final_filtered_results, conversation_metadata_result_set.next_page_id
    )


# ---------------------------------------------------------------------------
# Detail / CRUD
# ---------------------------------------------------------------------------


async def get_conversation_details(
    conversation_id: str,
    conversation_store: Any | None = None,
    user_id: str | None = None,
) -> ConversationInfo | None:
    """Retrieve detailed conversation information without FastAPI dependencies."""
    store = await resolve_conversation_store(conversation_store, user_id)
    if store is None:
        return None
    try:
        conversation = await store.get_metadata(conversation_id)
    except FileNotFoundError:
        return None

    manager = _require_conversation_manager()
    agent_loop_info_list = await manager.get_agent_loop_info(
        filter_to_sids={conversation_id}
    )
    agent_loop_info = agent_loop_info_list[0] if agent_loop_info_list else None
    connections = await manager.get_connections(conversation_id)
    num_connections = len(connections) if connections else 0

    return await get_conversation_info(conversation, num_connections, agent_loop_info)


async def delete_conversation_entry(
    conversation_id: str,
    user_id: str | None = None,
    conversation_store: Any | None = None,
) -> bool:
    """Delete a conversation, mirroring the behaviour of the HTTP endpoint."""
    store = await resolve_conversation_store(conversation_store, user_id)
    if store is None:
        return False
    try:
        await store.get_metadata(conversation_id)
    except FileNotFoundError:
        return False
    manager = _require_conversation_manager()
    if await manager.is_agent_loop_running(conversation_id):
        await manager.close_session(conversation_id)
    runtime_cls = get_runtime_cls(config.runtime)
    await runtime_cls.delete(conversation_id)
    await store.delete_metadata(conversation_id)
    return True


async def delete_all_conversations(
    user_id: str | None = None,
    conversation_store: Any | None = None,
) -> bool:
    """Delete all conversations for the given user."""
    store = await resolve_conversation_store(conversation_store, user_id)
    if store is None:
        return False

    manager = _require_conversation_manager()

    # Search for all conversations to close active sessions
    # Note: We might want to just tell the store to delete all, but we also
    # need to cleanup runtimes and active agent loops.
    # To be safe and thorough, we'll iterate through them.
    # However, if there are thousands, this might be slow.
    # For now, let's use the search to get the IDs.

    # Actually, let's just use the store's delete_all_metadata if possible,
    # but we MUST close all active sessions first.

    # TODO: In a production environment with many conversations, this should be a background task.
    search_result = await search_conversations(
        limit=1000, conversation_store=store, user_id=user_id
    )

    for conv in search_result.results:
        if await manager.is_agent_loop_running(conv.conversation_id):
            await manager.close_session(conv.conversation_id)
        try:
            runtime_cls = get_runtime_cls(config.runtime)
            await runtime_cls.delete(conv.conversation_id)
        except Exception as e:
            logger.warning("Failed to delete runtime for %s: %s", conv.conversation_id, e)

    await store.delete_all_metadata()
    return True

