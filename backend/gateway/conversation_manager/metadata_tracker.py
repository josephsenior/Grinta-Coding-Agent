"""Conversation metadata tracking — title, branch, cost, and git-event handling.

Extracted from :class:`LocalConversationManager` to keep that class
focused on session lifecycle and connection routing.  This tracker is
the single owner of metadata-mutation logic.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC
from typing import TYPE_CHECKING, Any

from backend.core.constants import CONVERSATION_METADATA_UPDATE_SYNC_TIMEOUT
from backend.core.logger import app_logger as logger
from backend.core.schemas import EventSource, ObservationType
from backend.ledger.action import MessageAction
from backend.ledger.observation.commands import CmdOutputObservation
from backend.gateway.constants import ROOM_KEY
from backend.utils.async_utils import (
    GENERAL_TIMEOUT,
    call_async_from_sync,
    run_in_loop,
)
from backend.utils.conversation_summary import (
    auto_generate_title,
    get_default_conversation_title,
)

if TYPE_CHECKING:
    import socketio  # type: ignore[import-untyped]

    from backend.inference.llm_registry import LLMRegistry
    from backend.gateway.session.session import Session
    from backend.persistence.conversation.conversation_store import ConversationStore
    from backend.persistence.data_models.conversation_metadata import ConversationMetadata
    from backend.persistence.data_models.settings import Settings
    from backend.persistence.files import FileStore


# Type alias for the session-lookup callable injected by the manager.
SessionLookup = Callable[[str], "Session | None"]


class ConversationMetadataTracker:
    """Owns all conversation-metadata mutations (title, branch, cost).

    Injected dependencies (constructor args) keep this class decoupled
    from the concrete ``LocalConversationManager``.
    """

    def __init__(
        self,
        sio: socketio.AsyncServer,
        file_store: FileStore,
        conversation_store_factory: Callable[[str | None], Any],
        session_lookup: SessionLookup,
        loop: asyncio.AbstractEventLoop | None = None,
    ) -> None:
        self._sio = sio
        self._file_store = file_store
        self._get_conversation_store = conversation_store_factory
        self._session_lookup = session_lookup
        self._loop = loop

    # ------------------------------------------------------------------ #
    # Public entry point
    # ------------------------------------------------------------------ #

    def create_update_callback(
        self,
        user_id: str | None,
        conversation_id: str,
        settings: Settings,
        llm_registry: LLMRegistry,
    ) -> Callable:
        """Return a *sync* callback suitable for ``EventStream.subscribe``.

        The callback bridges into the async metadata-update pipeline.
        """

        def callback(event: Any, *args: Any, **kwargs: Any) -> None:
            call_async_from_sync(
                self._update_conversation_for_event,
                CONVERSATION_METADATA_UPDATE_SYNC_TIMEOUT,
                user_id,
                conversation_id,
                settings,
                llm_registry,
                event,
            )

        return callback

    # ------------------------------------------------------------------ #
    # Core update orchestrator
    # ------------------------------------------------------------------ #

    async def _update_conversation_for_event(
        self,
        user_id: str | None,
        conversation_id: str,
        settings: Settings,
        llm_registry: LLMRegistry,
        event: Any = None,
    ) -> None:
        """Load metadata, apply metric / git / title updates, then save."""
        from datetime import datetime

        conversation_store: ConversationStore = await self._get_conversation_store(
            user_id
        )
        conversation = await conversation_store.get_metadata(conversation_id)
        conversation.last_updated_at = datetime.now(UTC)

        self._update_metrics_from_event(conversation, event)
        await self._handle_git_event(conversation_id, conversation, event)
        await self._update_conversation_title(
            conversation_id, conversation, user_id, settings, llm_registry, event
        )

        await conversation_store.save_metadata(conversation)

    # ------------------------------------------------------------------ #
    # Metrics
    # ------------------------------------------------------------------ #

    @staticmethod
    def _update_metrics_from_event(
        conversation: ConversationMetadata, event: Any
    ) -> None:
        if not event or not hasattr(event, "llm_metrics") or not event.llm_metrics:
            return

        metrics = event.llm_metrics

        if hasattr(metrics, "accumulated_cost"):
            conversation.accumulated_cost = metrics.accumulated_cost

        if hasattr(metrics, "accumulated_token_usage"):
            token_usage = metrics.accumulated_token_usage
            conversation.prompt_tokens = token_usage.prompt_tokens
            conversation.completion_tokens = token_usage.completion_tokens
            conversation.total_tokens = (
                token_usage.prompt_tokens + token_usage.completion_tokens
            )

    # ------------------------------------------------------------------ #
    # Git branch tracking
    # ------------------------------------------------------------------ #

    async def _handle_git_event(
        self, conversation_id: str, conversation: ConversationMetadata, event: Any
    ) -> None:
        if event and self._is_vcs_command_event(event):
            logger.info(
                "Git-related event detected, updating conversation branch for %s",
                conversation_id,
                extra={
                    "session_id": conversation_id,
                    "command": getattr(event, "command", "unknown"),
                },
            )
            await self._update_conversation_branch(conversation)

    @staticmethod
    def _is_vcs_command_event(event: Any) -> bool:
        if not event or not isinstance(event, CmdOutputObservation):
            return False
        if event.observation == ObservationType.RUN and event.metadata.exit_code == 0:
            command = event.command.lower()
            git_commands = [
                "git checkout",
                "git switch",
                "git merge",
                "git rebase",
                "git reset",
                "git branch",
            ]
            return any(git_cmd in command for git_cmd in git_commands)
        return False

    async def _update_conversation_branch(
        self, conversation: ConversationMetadata
    ) -> None:
        try:
            session, runtime = self._get_session_and_runtime(
                conversation.conversation_id
            )
            if not session or not runtime:
                return
            current_branch = self._get_current_workspace_branch(
                runtime, conversation.selected_repository
            )
            if self._should_update_branch(conversation.selected_branch, current_branch):
                self._update_branch_in_conversation(conversation, current_branch)
        except Exception as e:
            logger.warning(
                "Failed to update conversation branch: %s",
                e,
                extra={"session_id": conversation.conversation_id},
            )

    def _get_session_and_runtime(self, conversation_id: str) -> tuple[Any, Any]:
        session = self._session_lookup(conversation_id)
        if not session or not session.agent_session.runtime:
            return (None, None)
        return (session, session.agent_session.runtime)

    @staticmethod
    def _get_current_workspace_branch(
        runtime: Any, selected_repository: str | None
    ) -> str | None:
        if not selected_repository:
            primary_repo_path = None
        else:
            primary_repo_path = selected_repository.split("/")[-1]
        return runtime.get_workspace_branch(primary_repo_path)

    @staticmethod
    def _should_update_branch(
        current_branch: str | None, new_branch: str | None
    ) -> bool:
        return new_branch is not None and new_branch != current_branch

    @staticmethod
    def _update_branch_in_conversation(
        conversation: ConversationMetadata, new_branch: str | None
    ) -> None:
        old_branch = conversation.selected_branch
        conversation.selected_branch = new_branch
        logger.info(
            "Branch changed from %s to %s",
            old_branch,
            new_branch,
            extra={"session_id": conversation.conversation_id},
        )

    # ------------------------------------------------------------------ #
    # Title auto-generation
    # ------------------------------------------------------------------ #

    @staticmethod
    def _is_user_message_event(event: Any) -> bool:
        """True if event is a user message (triggers title generation)."""
        if not event:
            return False
        if not isinstance(event, MessageAction):
            return False
        src = getattr(event, "source", None)
        return src == EventSource.USER

    async def _update_conversation_title(
        self,
        conversation_id: str,
        conversation: ConversationMetadata,
        user_id: str | None,
        settings: Settings,
        llm_registry: LLMRegistry,
        event: Any = None,
    ) -> None:
        default_title = get_default_conversation_title(conversation_id)

        if conversation.title != default_title:
            return

        # Only run LLM title generation for user message events to avoid
        # 4+ concurrent Gemini calls (one per event) competing with the agent.
        if not self._is_user_message_event(event):
            return

        # Defer 5s so the agent's first LLM call gets priority (avoids 503/throttle).
        await asyncio.sleep(5)

        title = await auto_generate_title(
            conversation_id, user_id, self._file_store, settings, llm_registry
        )

        if title and not title.isspace():
            conversation.title = title
            await self._emit_title_update(conversation_id, title)
        else:
            conversation.title = default_title

    async def _emit_title_update(self, conversation_id: str, title: str) -> None:
        try:
            status_update_dict = {
                "status_update": True,
                "type": "info",
                "message": conversation_id,
                "conversation_title": title,
            }
            if self._loop is not None:
                await run_in_loop(
                    self._sio.emit(
                        "app_event",
                        status_update_dict,
                        to=ROOM_KEY.format(sid=conversation_id),
                    ),
                    self._loop,
                )
            else:
                await self._sio.emit(
                    "app_event",
                    status_update_dict,
                    to=ROOM_KEY.format(sid=conversation_id),
                )
        except Exception as e:
            logger.error("Error emitting title update event: %s", e)
