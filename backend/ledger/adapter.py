from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any

from backend.ledger.serialization.event import event_from_dict
from backend.ledger.stream import EventStream
from backend.persistence.files import FileStore


class EventServiceAdapter:
    """Simplified adapter for event services, supporting in-process EventStream.

    This replaces the more complex gRPC-capable adapter to streamline the codebase
    for platform-agnostic use.
    """

    def __init__(
        self,
        file_store_factory: Callable[[str | None], FileStore],
        use_grpc: bool = False,
        grpc_endpoint: str | None = None,
    ) -> None:
        """Initialize the adapter.

        Args:
            file_store_factory: Callable that returns a FileStore for a given user_id.
            use_grpc: Whether to use gRPC (currently not supported in this simplified version).
            grpc_endpoint: gRPC endpoint (currently not supported).
        """
        self.file_store_factory = file_store_factory
        if use_grpc:
            # We keep the parameter for compatibility but raise error if used
            raise RuntimeError(
                'gRPC mode is not available in this simplified EventServiceAdapter'
            )

        self._sessions: dict[str, dict[str, Any]] = {}
        self._streams: dict[str, EventStream] = {}

    def start_session(
        self,
        session_id: str | None = None,
        user_id: str | None = None,
        repository: str | None = None,
        branch: str | None = None,
        labels: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Start a new session and initialize its event stream."""
        if session_id is None:
            session_id = str(uuid.uuid4())

        session_info = {
            'session_id': session_id,
            'user_id': user_id,
            'repository': repository,
            'branch': branch,
            'labels': labels or {},
        }
        self._sessions[session_id] = session_info

        # Initialize EventStream for this session
        file_store = self.file_store_factory(user_id)
        stream = EventStream(session_id, file_store, user_id)
        self._streams[session_id] = stream

        return session_info

    def get_event_stream(self, session_id: str) -> EventStream:
        """Get the EventStream instance for a session."""
        if session_id not in self._streams:
            # Try to recover session if it exists in storage but not in memory
            # For now, we just raise error or create a new one if it's expected to exist
            session_info = self.get_session_info(session_id)
            if not session_info:
                raise ValueError(f'Session {session_id} not found')

            user_id = session_info.get('user_id')
            file_store = self.file_store_factory(user_id)
            self._streams[session_id] = EventStream(session_id, file_store, user_id)

        return self._streams[session_id]

    def publish_event(self, session_id: str, event_dict: dict[str, Any]) -> None:
        """Publish an event to a session's stream."""
        stream = self.get_event_stream(session_id)
        from backend.ledger import EventSource

        event = event_from_dict(event_dict)
        # EventStream.add_event requires (event, source)
        # Handle case where event.source might be None
        source = event.source if event.source is not None else EventSource.USER
        stream.add_event(event, source)

    def get_session_info(self, session_id: str) -> dict[str, Any] | None:
        """Get metadata for a session."""
        return self._sessions.get(session_id)
