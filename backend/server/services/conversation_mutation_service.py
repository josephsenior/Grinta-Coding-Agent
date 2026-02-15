"""Mutation operations for conversations.

Extracted from route handlers to keep them thin and testable.
Covers title updates, Socket.IO notifications, agent loop start/stop,
and playbook-specific conversation queries.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from backend.core.logger import FORGE_logger as logger
from backend.server.services.conversation_query_service import (
    build_conversation_result_set,
    filter_conversations_by_age,
    resolve_conversation_store,
)
from backend.server.services.shared_dependencies import (
    get_conversation_manager_instance,
    require_conversation_manager,
)
from backend.server.shared import config
from backend.storage.data_models.conversation_metadata import ConversationTrigger
from backend.storage.data_models.conversation_status import ConversationStatus

if TYPE_CHECKING:
    from backend.server.schemas.agent_loop_info import AgentLoopInfo
    from backend.server.schemas.conversation_info_result_set import (
        ConversationInfoResultSet,
    )
    from backend.storage.conversation.conversation_store import ConversationStore


# ---------------------------------------------------------------------------
# Title update
# ---------------------------------------------------------------------------


class TitleUpdateResult:
    """Outcome of a title-update attempt."""

    __slots__ = ("ok", "error_code", "error_message", "original_title", "new_title")

    def __init__(
        self,
        *,
        ok: bool,
        error_code: str | None = None,
        error_message: str | None = None,
        original_title: str | None = None,
        new_title: str | None = None,
    ) -> None:
        self.ok = ok
        self.error_code = error_code
        self.error_message = error_message
        self.original_title = original_title
        self.new_title = new_title


async def update_conversation_title(
    conversation_id: str,
    new_title: str,
    user_id: str | None,
    conversation_store: ConversationStore | None = None,
) -> TitleUpdateResult:
    """Update a conversation title and emit a Socket.IO notification.

    All business logic previously embedded in the PATCH route handler.
    """
    store = await resolve_conversation_store(conversation_store, user_id)
    if store is None:
        return TitleUpdateResult(
            ok=False,
            error_code="STORE$UNAVAILABLE",
            error_message="Conversation store unavailable",
        )

    try:
        metadata = await store.get_metadata(conversation_id)
    except FileNotFoundError:
        return TitleUpdateResult(
            ok=False,
            error_code="CONVERSATION$NOT_FOUND",
            error_message="Conversation not found",
        )

    if user_id and metadata.user_id != user_id:
        return TitleUpdateResult(
            ok=False,
            error_code="AUTHORIZATION$PERMISSION_DENIED",
            error_message="Permission denied: You can only update your own conversations",
        )

    original_title = metadata.title
    metadata.title = new_title.strip()

    # Monotonic timestamp guard
    new_timestamp = datetime.now(UTC)
    if metadata.last_updated_at and new_timestamp <= metadata.last_updated_at:
        new_timestamp = metadata.last_updated_at + timedelta(microseconds=1)
    metadata.last_updated_at = new_timestamp

    await store.save_metadata(metadata)

    # Best-effort Socket.IO notification
    manager = get_conversation_manager_instance()
    if manager is not None:
        sio = getattr(manager, "sio", None)
        if sio is not None:
            try:
                await sio.emit(
                    "forge_event",
                    {
                        "status_update": True,
                        "type": "info",
                        "message": conversation_id,
                        "conversation_title": metadata.title,
                    },
                    to=f"room:{conversation_id}",
                )
            except Exception as exc:
                logger.error("Error emitting title update event: %s", exc)

    logger.info(
        'Updated conversation %s title from "%s" to "%s"',
        conversation_id,
        original_title,
        metadata.title,
    )
    return TitleUpdateResult(
        ok=True, original_title=original_title, new_title=metadata.title
    )


# ---------------------------------------------------------------------------
# Playbook-management query
# ---------------------------------------------------------------------------


async def search_playbook_conversations(
    selected_repository: str,
    page_id: str | None,
    limit: int,
    conversation_store: ConversationStore | None,
    provider_tokens: Any | None,
) -> ConversationInfoResultSet:
    """Query conversations triggered by playbook management.

    Filters by repository, trigger type, and open-PR status.
    Extracted from the GET /playbook-management/conversations handler.
    """
    from backend.server.services.session_init_service import normalize_provider_tokens

    store = await resolve_conversation_store(conversation_store)
    if store is None:
        return ConversationInfoResultSet(results=[], next_page_id=None)
    normalize_provider_tokens(provider_tokens)  # validate tokens

    result_set = await store.search(page_id, limit)
    aged = filter_conversations_by_age(
        result_set.results, config.conversation_max_age_seconds
    )

    final: list = []
    for conv in aged:
        if conv.trigger != ConversationTrigger.PLAYBOOK_MANAGEMENT:
            continue
        if conv.selected_repository != selected_repository:
            continue
        final.append(conv)

    return await build_conversation_result_set(final, result_set.next_page_id)


# ---------------------------------------------------------------------------
# Agent loop start / stop
# ---------------------------------------------------------------------------


class AgentLoopResult:
    """Outcome of an agent-loop start or stop attempt."""

    __slots__ = ("ok", "error_code", "error_message", "conversation_status", "message")

    def __init__(
        self,
        *,
        ok: bool,
        error_code: str | None = None,
        error_message: str | None = None,
        conversation_status: ConversationStatus | None = None,
        message: str | None = None,
    ) -> None:
        self.ok = ok
        self.error_code = error_code
        self.error_message = error_message
        self.conversation_status = conversation_status
        self.message = message


async def start_agent_loop(
    conversation_id: str,
    user_id: str,
    provider_tokens: Any | None,
    providers_list: list[Any],
    conversation_store: ConversationStore | None = None,
) -> AgentLoopResult:
    """Resolve metadata, configure settings, and start the agent loop.

    Encapsulates the business logic previously inlined in the
    ``start_conversation`` route handler.
    """
    from backend.server.services.conversation_service import (
        setup_init_conversation_settings,
    )
    from backend.server.services.session_init_service import normalize_provider_tokens

    store = await resolve_conversation_store(conversation_store, user_id)
    if store is None:
        return AgentLoopResult(
            ok=False,
            error_code="STORE$UNAVAILABLE",
            error_message="Conversation store unavailable",
        )
    normalized_tokens = normalize_provider_tokens(provider_tokens)

    try:
        await store.get_metadata(conversation_id)
    except Exception:
        return AgentLoopResult(
            ok=False,
            error_code="CONVERSATION_NOT_FOUND",
            error_message="Conversation not found",
        )

    manager = require_conversation_manager()
    conversation_init_data = await setup_init_conversation_settings(
        user_id,
        conversation_id,
        providers_list,
        normalized_tokens,
    )
    agent_loop_info: AgentLoopInfo = await manager.maybe_start_agent_loop(
        sid=conversation_id,
        settings=conversation_init_data,
        user_id=user_id,
    )
    return AgentLoopResult(
        ok=True,
        conversation_status=agent_loop_info.status,
    )


async def stop_agent_loop(
    conversation_id: str,
    user_id: str,
) -> AgentLoopResult:
    """Check running status and close the session.

    Encapsulates the business logic previously inlined in the
    ``stop_conversation`` route handler.
    """
    manager = require_conversation_manager()
    agent_loop_info = await manager.get_agent_loop_info(
        user_id=user_id,
        filter_to_sids={conversation_id},
    )
    conversation_status = (
        agent_loop_info[0].status if agent_loop_info else ConversationStatus.STOPPED
    )
    if conversation_status not in (
        ConversationStatus.STARTING,
        ConversationStatus.RUNNING,
    ):
        return AgentLoopResult(
            ok=True,
            conversation_status=conversation_status,
            message="Conversation was not running",
        )
    await manager.close_session(conversation_id)
    return AgentLoopResult(
        ok=True,
        conversation_status=conversation_status,
        message="Conversation stopped successfully",
    )
