"""Socket.IO connection management and message queuing.

Provides:
- Connection health monitoring with heartbeat tracking
- Message queuing for disconnected clients
- Presence awareness
- Connection limits per user/IP
- Stale connection detection and cleanup
"""

from __future__ import annotations

import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from backend.core.logger import forge_logger as logger

if TYPE_CHECKING:
    import socketio  # type: ignore[import-untyped]

# ---------------------------------------------------------------------------
# Heartbeat configuration
# ---------------------------------------------------------------------------
_HEARTBEAT_STALE_THRESHOLD = 90  # seconds — consider stale if no ping received


@dataclass
class ConnectionInfo:
    """Information about a Socket.IO connection."""

    sid: str
    user_id: str | None = None
    conversation_id: str | None = None
    connected_at: float = field(default_factory=time.time)
    last_activity: float = field(default_factory=time.time)
    last_heartbeat: float = field(default_factory=time.time)
    message_queue: deque = field(default_factory=deque)
    max_queue_size: int = 100


class SocketIOConnectionManager:
    """Manages Socket.IO connections with queuing and presence."""

    def __init__(self):
        """Initialize connection manager."""
        self._connections: dict[str, ConnectionInfo] = {}
        self._user_connections: dict[str, set[str]] = defaultdict(set)
        self._conversation_connections: dict[str, set[str]] = defaultdict(set)
        self._max_connections_per_user = 10
        self._max_connections_per_ip = 20
        self._message_queue_ttl = 300  # 5 minutes

    def register_connection(
        self,
        sid: str,
        user_id: str | None = None,
        conversation_id: str | None = None,
    ) -> ConnectionInfo:
        """Register a new connection.

        Args:
            sid: Socket session ID
            user_id: User ID (optional)
            conversation_id: Conversation ID (optional)

        Returns:
            ConnectionInfo instance

        Raises:
            ValueError: If connection limits are exceeded
        """
        # Check connection limits
        if user_id:
            user_conns = self._user_connections.get(user_id, set())
            if len(user_conns) >= self._max_connections_per_user:
                raise ValueError(
                    f"Maximum connections per user ({self._max_connections_per_user}) exceeded"
                )

        conn_info = ConnectionInfo(
            sid=sid,
            user_id=user_id,
            conversation_id=conversation_id,
        )

        self._connections[sid] = conn_info

        if user_id:
            self._user_connections[user_id].add(sid)

        if conversation_id:
            self._conversation_connections[conversation_id].add(sid)

        logger.info(
            "Connection registered: sid=%s, user_id=%s, conversation_id=%s",
            sid,
            user_id,
            conversation_id,
        )

        return conn_info

    def unregister_connection(self, sid: str) -> None:
        """Unregister a connection.

        Args:
            sid: Socket session ID
        """
        conn_info = self._connections.pop(sid, None)
        if not conn_info:
            return

        if conn_info.user_id:
            self._user_connections[conn_info.user_id].discard(sid)
            if not self._user_connections[conn_info.user_id]:
                del self._user_connections[conn_info.user_id]

        if conn_info.conversation_id:
            self._conversation_connections[conn_info.conversation_id].discard(sid)
            if not self._conversation_connections[conn_info.conversation_id]:
                del self._conversation_connections[conn_info.conversation_id]

        logger.info("Connection unregistered: sid=%s", sid)

    def get_connection(self, sid: str) -> ConnectionInfo | None:
        """Get connection information.

        Args:
            sid: Socket session ID

        Returns:
            ConnectionInfo or None if not found
        """
        return self._connections.get(sid)

    def update_activity(self, sid: str) -> None:
        """Update last activity time for a connection.

        Args:
            sid: Socket session ID
        """
        conn_info = self._connections.get(sid)
        if conn_info:
            conn_info.last_activity = time.time()

    def queue_message(self, sid: str, event: str, data: Any) -> bool:
        """Queue a message for a connection.

        Args:
            sid: Socket session ID
            event: Event name
            data: Event data

        Returns:
            True if queued, False if queue full
        """
        conn_info = self._connections.get(sid)
        if not conn_info:
            return False

        if len(conn_info.message_queue) >= conn_info.max_queue_size:
            logger.warning("Message queue full for connection %s", sid)
            return False

        conn_info.message_queue.append((event, data, time.time()))
        return True

    async def deliver_queued_messages(self, sid: str, sio: socketio.AsyncServer) -> int:
        """Deliver queued messages to a connection.

        Args:
            sid: Socket session ID
            sio: Socket.IO server instance

        Returns:
            Number of messages delivered
        """
        conn_info = self._connections.get(sid)
        if not conn_info or not conn_info.message_queue:
            return 0

        delivered = 0
        now = time.time()

        while conn_info.message_queue:
            event, data, queued_at = conn_info.message_queue[0]

            # Check TTL
            if now - queued_at > self._message_queue_ttl:
                conn_info.message_queue.popleft()
                logger.debug("Dropped expired message for %s", sid)
                continue

            try:
                await sio.emit(event, data, room=sid)
                conn_info.message_queue.popleft()
                delivered += 1
            except Exception as e:
                logger.error("Error delivering queued message to %s: %s", sid, e)
                break

        if delivered > 0:
            logger.info("Delivered %s queued messages to %s", delivered, sid)

        return delivered

    def get_conversation_connections(self, conversation_id: str) -> list[str]:
        """Get all connection IDs for a conversation.

        Args:
            conversation_id: Conversation ID

        Returns:
            List of socket session IDs
        """
        return list(self._conversation_connections.get(conversation_id, set()))

    def get_user_connections(self, user_id: str) -> list[str]:
        """Get all connection IDs for a user.

        Args:
            user_id: User ID

        Returns:
            List of socket session IDs
        """
        return list(self._user_connections.get(user_id, set()))

    def get_presence(self, conversation_id: str) -> dict[str, Any]:
        """Get presence information for a conversation.

        Args:
            conversation_id: Conversation ID

        Returns:
            Presence information (user IDs, connection count, etc.)
        """
        sids = self.get_conversation_connections(conversation_id)
        users = set()

        for sid in sids:
            conn_info = self._connections.get(sid)
            if conn_info and conn_info.user_id:
                users.add(conn_info.user_id)

        return {
            "conversation_id": conversation_id,
            "connection_count": len(sids),
            "user_ids": list(users),
            "active_users": len(users),
        }

    def cleanup_idle_connections(self, idle_timeout: float = 3600) -> int:
        """Clean up idle connections.

        Args:
            idle_timeout: Idle timeout in seconds (default: 1 hour)

        Returns:
            Number of connections cleaned up
        """
        now = time.time()
        to_remove = []

        for sid, conn_info in self._connections.items():
            if now - conn_info.last_activity > idle_timeout:
                to_remove.append(sid)

        for sid in to_remove:
            self.unregister_connection(sid)

        if to_remove:
            logger.info("Cleaned up %s idle connections", len(to_remove))

        return len(to_remove)

    # ── heartbeat tracking ────────────────────────────────────────

    def record_heartbeat(self, sid: str) -> None:
        """Record a heartbeat ping from a client.

        Args:
            sid: Socket session ID
        """
        conn_info = self._connections.get(sid)
        if conn_info:
            conn_info.last_heartbeat = time.time()
            conn_info.last_activity = time.time()

    def get_stale_connections(
        self,
        stale_threshold: float = _HEARTBEAT_STALE_THRESHOLD,
    ) -> list[str]:
        """Return SIDs that have not sent a heartbeat within *stale_threshold*.

        Args:
            stale_threshold: Seconds since last heartbeat to consider stale.

        Returns:
            List of stale socket session IDs.
        """
        now = time.time()
        return [
            sid
            for sid, info in self._connections.items()
            if now - info.last_heartbeat > stale_threshold
        ]

    def cleanup_stale_connections(
        self,
        stale_threshold: float = _HEARTBEAT_STALE_THRESHOLD,
    ) -> int:
        """Unregister connections that have not sent a heartbeat recently.

        Returns:
            Number of connections removed.
        """
        stale = self.get_stale_connections(stale_threshold)
        for sid in stale:
            self.unregister_connection(sid)
        if stale:
            logger.info("Cleaned up %d stale (no heartbeat) connections", len(stale))
        return len(stale)


# Global connection manager instance
_connection_manager: SocketIOConnectionManager | None = None


def get_connection_manager() -> SocketIOConnectionManager:
    """Get or create global connection manager instance.

    Returns:
        SocketIOConnectionManager instance
    """
    global _connection_manager
    if _connection_manager is None:
        _connection_manager = SocketIOConnectionManager()
    return _connection_manager
