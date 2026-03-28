"""Tests for Socket.IO resilience improvements.

Covers:
- ForgeClient: exponential backoff config, offline queue, heartbeat, auto-rejoin
- SocketIOConnectionManager: heartbeat tracking, stale connection cleanup
"""

from __future__ import annotations

import asyncio
import time
from collections import deque
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.gateway.middleware.socketio_connection_manager import (
    ConnectionInfo,
    SocketIOConnectionManager,
)


# ---------------------------------------------------------------------------
# SocketIOConnectionManager tests
# ---------------------------------------------------------------------------


class TestConnectionManagerHeartbeat:
    """Heartbeat tracking and stale connection cleanup."""

    def _make_manager(self) -> SocketIOConnectionManager:
        return SocketIOConnectionManager()

    def test_record_heartbeat_updates_timestamps(self):
        mgr = self._make_manager()
        info = mgr.register_connection("sid-1", user_id="u1")
        old_hb = info.last_heartbeat

        time.sleep(0.01)
        mgr.record_heartbeat("sid-1")

        assert info.last_heartbeat > old_hb
        assert info.last_activity >= info.last_heartbeat

    def test_record_heartbeat_missing_sid_is_noop(self):
        mgr = self._make_manager()
        mgr.record_heartbeat("nonexistent")  # should not raise

    def test_stale_connections_detected(self):
        mgr = self._make_manager()
        info = mgr.register_connection("sid-old")
        # Simulate stale by backdating heartbeat
        info.last_heartbeat = time.time() - 200

        stale = mgr.get_stale_connections(stale_threshold=100)
        assert "sid-old" in stale

    def test_fresh_connections_not_stale(self):
        mgr = self._make_manager()
        mgr.register_connection("sid-fresh")
        mgr.record_heartbeat("sid-fresh")

        stale = mgr.get_stale_connections(stale_threshold=100)
        assert "sid-fresh" not in stale

    def test_cleanup_stale_removes_connections(self):
        mgr = self._make_manager()
        info = mgr.register_connection("stale-1", user_id="u1")
        info.last_heartbeat = time.time() - 300
        mgr.register_connection("fresh-1", user_id="u2")
        mgr.record_heartbeat("fresh-1")

        removed = mgr.cleanup_stale_connections(stale_threshold=100)
        assert removed == 1
        assert mgr.get_connection("stale-1") is None
        assert mgr.get_connection("fresh-1") is not None

    def test_connection_info_has_heartbeat_field(self):
        info = ConnectionInfo(sid="test")
        assert hasattr(info, "last_heartbeat")
        assert info.last_heartbeat > 0


class TestConnectionManagerQueueDelivery:
    """Message queuing and delivery edge cases."""

    def _make_manager(self) -> SocketIOConnectionManager:
        return SocketIOConnectionManager()

    def test_queue_message_returns_false_for_unknown_sid(self):
        mgr = self._make_manager()
        assert mgr.queue_message("unknown", "event", {}) is False

    def test_queue_message_respects_max_size(self):
        mgr = self._make_manager()
        info = mgr.register_connection("sid-1")
        info.max_queue_size = 2

        assert mgr.queue_message("sid-1", "e", {"a": 1}) is True
        assert mgr.queue_message("sid-1", "e", {"a": 2}) is True
        assert mgr.queue_message("sid-1", "e", {"a": 3}) is False

    @pytest.mark.asyncio
    async def test_deliver_queued_messages_expired(self):
        mgr = self._make_manager()
        mgr.register_connection("sid-1")
        mgr._message_queue_ttl = 0  # expire immediately
        mgr.queue_message("sid-1", "event", {"x": 1})
        time.sleep(0.01)

        sio = AsyncMock()
        delivered = await mgr.deliver_queued_messages("sid-1", sio)
        assert delivered == 0
        sio.emit.assert_not_called()

    @pytest.mark.asyncio
    async def test_deliver_queued_messages_success(self):
        mgr = self._make_manager()
        mgr.register_connection("sid-1")
        mgr.queue_message("sid-1", "forge_event", {"data": "hello"})

        sio = AsyncMock()
        delivered = await mgr.deliver_queued_messages("sid-1", sio)
        assert delivered == 1
        sio.emit.assert_called_once_with("forge_event", {"data": "hello"}, room="sid-1")


# ---------------------------------------------------------------------------
# ForgeClient resilience tests
# ---------------------------------------------------------------------------


class TestForgeClientResilience:
    """Test client-side resilience features without real network."""

    def _make_client(self):
        """Create a ForgeClient with mocked transports."""
        from forge_client import ForgeClient

        client = ForgeClient.__new__(ForgeClient)
        client.base_url = "http://localhost:3000"
        client._http = AsyncMock()
        client._sio = MagicMock()
        client._sio.connected = False
        client._sio.emit = AsyncMock()
        client._sio.event = MagicMock(side_effect=lambda fn: fn)
        client._sio.on = MagicMock(side_effect=lambda name: (lambda fn: fn))
        client._event_callback = None
        client._connected_conversation_id = None
        client._connect_event = asyncio.Event()
        client._offline_queue = deque(maxlen=200)
        client._heartbeat_task = None
        return client

    @pytest.mark.asyncio
    async def test_send_message_buffers_when_disconnected(self):
        client = self._make_client()
        client._sio.connected = False

        await client.send_message("hello offline")
        assert len(client._offline_queue) == 1
        event, payload = client._offline_queue[0]
        assert event == "forge_user_action"
        assert payload["args"]["content"] == "hello offline"

    @pytest.mark.asyncio
    async def test_send_message_emits_when_connected(self):
        client = self._make_client()
        client._sio.connected = True

        await client.send_message("hello online")
        client._sio.emit.assert_called_once()
        assert not client._offline_queue

    @pytest.mark.asyncio
    async def test_send_confirmation_buffers_when_disconnected(self):
        client = self._make_client()
        client._sio.connected = False

        await client.send_confirmation(confirm=True)
        assert len(client._offline_queue) == 1

    @pytest.mark.asyncio
    async def test_flush_offline_queue(self):
        client = self._make_client()
        client._sio.connected = True
        client._offline_queue.append(("forge_user_action", {"action": "msg"}))
        client._offline_queue.append(("forge_user_action", {"action": "msg2"}))

        await client._flush_offline_queue()
        assert not client._offline_queue
        assert client._sio.emit.call_count == 2

    @pytest.mark.asyncio
    async def test_flush_offline_queue_requeues_on_failure(self):
        client = self._make_client()
        client._sio.connected = True
        client._sio.emit = AsyncMock(side_effect=Exception("network error"))
        client._offline_queue.append(("forge_user_action", {"action": "msg"}))

        await client._flush_offline_queue()
        # Should be re-queued
        assert len(client._offline_queue) == 1

    @pytest.mark.asyncio
    async def test_buffer_action_respects_max_size(self):
        client = self._make_client()
        client._offline_queue = deque(maxlen=3)

        for i in range(5):
            client._buffer_action("evt", {"i": i})

        assert len(client._offline_queue) == 3
        # Oldest should have been evicted
        _, payload = client._offline_queue[0]
        assert payload["i"] == 2

    def test_sio_configured_with_exponential_backoff(self):
        """Verify the AsyncClient is created with backoff settings."""
        from forge_client.client import (
            ForgeClient,
            _RECONNECT_ATTEMPTS,
            _RECONNECT_DELAY_MAX,
            _RECONNECT_DELAY_MIN,
        )

        client = ForgeClient(base_url="http://localhost:3000")
        assert client._sio.reconnection is True
        assert client._sio.reconnection_delay == _RECONNECT_DELAY_MIN
        assert client._sio.reconnection_delay_max == _RECONNECT_DELAY_MAX
        assert client._sio.reconnection_attempts == _RECONNECT_ATTEMPTS

    def test_is_ws_connected_property(self):
        client = self._make_client()
        client._sio.connected = True
        assert client.is_ws_connected is True
        client._sio.connected = False
        assert client.is_ws_connected is False
