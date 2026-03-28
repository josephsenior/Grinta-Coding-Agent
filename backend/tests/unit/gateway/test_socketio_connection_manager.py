"""Tests for backend.gateway.middleware.socketio_connection_manager."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock

import pytest

from backend.gateway.middleware.socketio_connection_manager import (
    ConnectionInfo,
    SocketIOConnectionManager,
)


@pytest.fixture
def mgr():
    return SocketIOConnectionManager()


# ---------------------------------------------------------------------------
# ConnectionInfo dataclass
# ---------------------------------------------------------------------------
class TestConnectionInfo:
    def test_defaults(self):
        ci = ConnectionInfo(sid="abc")
        assert ci.sid == "abc"
        assert ci.user_id is None
        assert ci.conversation_id is None
        assert ci.connected_at > 0
        assert ci.last_activity > 0
        assert not ci.message_queue
        assert ci.max_queue_size == 100


# ---------------------------------------------------------------------------
# register / unregister
# ---------------------------------------------------------------------------
class TestRegisterUnregister:
    def test_register(self, mgr):
        ci = mgr.register_connection("s1", user_id="u1", conversation_id="c1")
        assert ci.sid == "s1"
        assert mgr.get_connection("s1") is ci
        assert "s1" in mgr.get_user_connections("u1")
        assert "s1" in mgr.get_conversation_connections("c1")

    def test_register_no_user(self, mgr):
        ci = mgr.register_connection("s1")
        assert ci.user_id is None

    def test_unregister(self, mgr):
        mgr.register_connection("s1", user_id="u1", conversation_id="c1")
        mgr.unregister_connection("s1")
        assert mgr.get_connection("s1") is None
        assert mgr.get_user_connections("u1") == []
        assert mgr.get_conversation_connections("c1") == []

    def test_unregister_unknown(self, mgr):
        mgr.unregister_connection("unknown")  # Should not raise

    def test_connection_limit(self, mgr):
        mgr._max_connections_per_user = 2
        mgr.register_connection("s1", user_id="u1")
        mgr.register_connection("s2", user_id="u1")
        with pytest.raises(ValueError, match="Maximum connections"):
            mgr.register_connection("s3", user_id="u1")


# ---------------------------------------------------------------------------
# update_activity
# ---------------------------------------------------------------------------
class TestUpdateActivity:
    def test_updates_time(self, mgr):
        mgr.register_connection("s1")
        ci = mgr.get_connection("s1")
        old_time = ci.last_activity
        time.sleep(0.01)
        mgr.update_activity("s1")
        assert ci.last_activity >= old_time

    def test_unknown_sid(self, mgr):
        mgr.update_activity("unknown")  # Should not raise


# ---------------------------------------------------------------------------
# message queuing
# ---------------------------------------------------------------------------
class TestMessageQueuing:
    def test_queue_message(self, mgr):
        mgr.register_connection("s1")
        assert mgr.queue_message("s1", "event", {"data": 1}) is True
        ci = mgr.get_connection("s1")
        assert len(ci.message_queue) == 1

    def test_queue_unknown_sid(self, mgr):
        assert mgr.queue_message("unknown", "e", {}) is False

    def test_queue_full(self, mgr):
        mgr.register_connection("s1")
        ci = mgr.get_connection("s1")
        ci.max_queue_size = 2
        mgr.queue_message("s1", "e1", {})
        mgr.queue_message("s1", "e2", {})
        assert mgr.queue_message("s1", "e3", {}) is False

    @pytest.mark.asyncio
    async def test_deliver_queued(self, mgr):
        mgr.register_connection("s1")
        mgr.queue_message("s1", "event", {"x": 1})
        sio = AsyncMock()
        delivered = await mgr.deliver_queued_messages("s1", sio)
        assert delivered == 1
        sio.emit.assert_called_once_with("event", {"x": 1}, room="s1")
        ci = mgr.get_connection("s1")
        assert not ci.message_queue

    @pytest.mark.asyncio
    async def test_deliver_expired(self, mgr):
        mgr.register_connection("s1")
        ci = mgr.get_connection("s1")
        # Manually add an expired message
        ci.message_queue.append(("old", {}, time.time() - 600))
        mgr._message_queue_ttl = 300
        sio = AsyncMock()
        delivered = await mgr.deliver_queued_messages("s1", sio)
        assert delivered == 0
        sio.emit.assert_not_called()

    @pytest.mark.asyncio
    async def test_deliver_empty_queue(self, mgr):
        mgr.register_connection("s1")
        sio = AsyncMock()
        delivered = await mgr.deliver_queued_messages("s1", sio)
        assert delivered == 0

    @pytest.mark.asyncio
    async def test_deliver_unknown_sid(self, mgr):
        sio = AsyncMock()
        delivered = await mgr.deliver_queued_messages("unknown", sio)
        assert delivered == 0

    @pytest.mark.asyncio
    async def test_deliver_emit_error(self, mgr):
        mgr.register_connection("s1")
        mgr.queue_message("s1", "e1", {})
        mgr.queue_message("s1", "e2", {})
        sio = AsyncMock()
        sio.emit.side_effect = Exception("disconnected")
        delivered = await mgr.deliver_queued_messages("s1", sio)
        assert delivered == 0
        # Messages stay in queue
        ci = mgr.get_connection("s1")
        assert len(ci.message_queue) == 2


# ---------------------------------------------------------------------------
# get_presence
# ---------------------------------------------------------------------------
class TestPresence:
    def test_basic_presence(self, mgr):
        mgr.register_connection("s1", user_id="u1", conversation_id="c1")
        mgr.register_connection("s2", user_id="u2", conversation_id="c1")
        presence = mgr.get_presence("c1")
        assert presence["connection_count"] == 2
        assert presence["active_users"] == 2
        assert set(presence["user_ids"]) == {"u1", "u2"}
        assert presence["conversation_id"] == "c1"

    def test_no_connections(self, mgr):
        presence = mgr.get_presence("c1")
        assert presence["connection_count"] == 0
        assert presence["active_users"] == 0


# ---------------------------------------------------------------------------
# cleanup
# ---------------------------------------------------------------------------
class TestCleanup:
    def test_cleanup_idle(self, mgr):
        mgr.register_connection("s1", user_id="u1")
        ci = mgr.get_connection("s1")
        ci.last_activity = time.time() - 7200  # 2 hours ago
        cleaned = mgr.cleanup_idle_connections(idle_timeout=3600)
        assert cleaned == 1
        assert mgr.get_connection("s1") is None

    def test_cleanup_active_not_removed(self, mgr):
        mgr.register_connection("s1")
        cleaned = mgr.cleanup_idle_connections(idle_timeout=3600)
        assert cleaned == 0
        assert mgr.get_connection("s1") is not None

    def test_cleanup_mixed(self, mgr):
        mgr.register_connection("s1")
        mgr.register_connection("s2")
        ci2 = mgr.get_connection("s2")
        ci2.last_activity = time.time() - 7200
        cleaned = mgr.cleanup_idle_connections(idle_timeout=3600)
        assert cleaned == 1
        assert mgr.get_connection("s1") is not None
        assert mgr.get_connection("s2") is None


# ---------------------------------------------------------------------------
# get_connection_manager singleton
# ---------------------------------------------------------------------------
class TestGetConnectionManager:
    def test_singleton(self):
        import backend.gateway.middleware.socketio_connection_manager as mod

        old = mod._connection_manager
        try:
            mod._connection_manager = None
            m1 = mod.get_connection_manager()
            m2 = mod.get_connection_manager()
            assert m1 is m2
        finally:
            mod._connection_manager = old
