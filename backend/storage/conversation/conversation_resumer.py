"""Unified conversation resume API.

Ties together event replay, state checkpoints, and conversation metadata
into a single entry-point for restoring a session from disk.

Usage::

    resumer = ConversationResumer(file_store)
    snapshot = await resumer.load(session_id)
    if snapshot:
        print(snapshot.metadata)     # ConversationMetadata
        print(len(snapshot.events))  # replayed events
        print(snapshot.state)        # last checkpoint State or None

"""

from __future__ import annotations

import dataclasses
import logging
from typing import TYPE_CHECKING, Any

from backend.events.serialization.event import event_from_dict
from backend.storage.locations import (
    get_conversation_events_dir,
    get_conversation_metadata_filename,
)

if TYPE_CHECKING:
    from backend.events.event import Event
    from backend.storage import FileStore

logger = logging.getLogger(__name__)


@dataclasses.dataclass(frozen=True)
class ConversationSnapshot:
    """Immutable snapshot of a persisted conversation."""

    session_id: str
    metadata: dict[str, Any]
    events: list[Event]
    state: dict[str, Any] | None
    checkpoint_name: str | None


class ConversationResumer:
    """Loads a full conversation snapshot from the file store.

    Combines:
    - Conversation metadata (``metadata.json``)
    - Ordered event replay (``events/*.json``)
    - Latest checkpoint state (if available)
    """

    def __init__(self, file_store: FileStore, user_id: str | None = None) -> None:
        self._fs = file_store
        self._user_id = user_id

    async def load(self, session_id: str) -> ConversationSnapshot | None:
        """Load and reconstruct a conversation from storage.

        Returns ``None`` if the session does not exist.
        """
        try:
            metadata = await self._load_metadata(session_id)
        except FileNotFoundError:
            return None

        events = await self._replay_events(session_id)
        state, checkpoint_name = await self._load_latest_checkpoint(session_id)

        return ConversationSnapshot(
            session_id=session_id,
            metadata=metadata,
            events=events,
            state=state,
            checkpoint_name=checkpoint_name,
        )

    async def list_sessions(self) -> list[str]:
        """Return known session IDs from the file store."""
        from backend.core.constants import CONVERSATION_BASE_DIR
        from backend.utils.async_utils import call_sync_from_async

        try:
            entries = await call_sync_from_async(self._fs.list, CONVERSATION_BASE_DIR)
            return [e.rstrip("/") for e in entries if not e.startswith(".")]
        except FileNotFoundError:
            return []

    # ------------------------------------------------------------------ #
    # Internal helpers                                                    #
    # ------------------------------------------------------------------ #
    async def _load_metadata(self, sid: str) -> dict[str, Any]:
        import json

        from backend.utils.async_utils import call_sync_from_async

        path = get_conversation_metadata_filename(sid, self._user_id)
        raw = await call_sync_from_async(self._fs.read, path)
        return json.loads(raw)  # type: ignore[arg-type]

    async def _replay_events(self, sid: str) -> list[Event]:
        """Read and deserialize all events in order."""
        import json

        from backend.utils.async_utils import call_sync_from_async

        events_dir = get_conversation_events_dir(sid, self._user_id)
        try:
            files = await call_sync_from_async(self._fs.list, events_dir)
        except FileNotFoundError:
            return []

        # Sort by numeric ID
        json_files = [
            f for f in files if f.endswith(".json") and not f.endswith(".pending")
        ]
        json_files.sort(key=lambda f: int(f.replace(".json", "")))

        events: list[Event] = []
        for fname in json_files:
            try:
                raw = await call_sync_from_async(self._fs.read, f"{events_dir}{fname}")
                data = json.loads(raw)
                events.append(event_from_dict(data))
            except Exception as exc:
                logger.warning("Skipping corrupt event %s: %s", fname, exc)
        return events

    async def _load_latest_checkpoint(
        self, sid: str
    ) -> tuple[dict[str, Any] | None, str | None]:
        """Load the most recent checkpoint state, if any."""
        from backend.controller.state.session_checkpoint_manager import (
            SessionCheckpointManager,
        )

        mgr = SessionCheckpointManager(sid, self._fs, self._user_id)
        names = mgr.list_checkpoints()
        if not names:
            return None, None
        # Pick last (most recent by convention)
        latest = names[-1]
        state = mgr.restore_checkpoint(latest)
        if state is None:
            return None, None
        # Convert State to dict for portability
        state_dict: dict[str, Any] = {}
        if hasattr(state, "__dict__"):
            state_dict = {
                k: v for k, v in state.__dict__.items() if not k.startswith("_")
            }
        return state_dict, latest
