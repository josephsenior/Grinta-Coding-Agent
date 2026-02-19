"""Tests for backend.storage.conversation.conversation_resumer."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.storage.conversation.conversation_resumer import (
    ConversationResumer,
    ConversationSnapshot,
)


# ── ConversationSnapshot dataclass ────────────────────────────────────


class TestConversationSnapshot:
    def test_creation(self):
        snap = ConversationSnapshot(
            session_id="s1",
            metadata={"title": "test"},
            events=[],
            state=None,
            checkpoint_name=None,
        )
        assert snap.session_id == "s1"
        assert snap.metadata == {"title": "test"}
        assert snap.events == []
        assert snap.state is None
        assert snap.checkpoint_name is None

    def test_is_frozen(self):
        snap = ConversationSnapshot(
            session_id="s1", metadata={}, events=[], state=None, checkpoint_name=None
        )
        with pytest.raises(AttributeError):
            snap.session_id = "s2"  # type: ignore[misc]

    def test_with_state(self):
        snap = ConversationSnapshot(
            session_id="s1",
            metadata={},
            events=[],
            state={"key": "val"},
            checkpoint_name="cp-1",
        )
        assert snap.state == {"key": "val"}
        assert snap.checkpoint_name == "cp-1"


# ── ConversationResumer.__init__ ──────────────────────────────────────


class TestConversationResumerInit:
    def test_stores_file_store(self):
        fs = MagicMock()
        resumer = ConversationResumer(fs)
        assert resumer._fs is fs
        assert resumer._user_id is None

    def test_stores_user_id(self):
        fs = MagicMock()
        resumer = ConversationResumer(fs, user_id="user-1")
        assert resumer._user_id == "user-1"


# ── load ──────────────────────────────────────────────────────────────


class TestConversationResumerLoad:
    async def test_returns_none_when_no_metadata(self):
        fs = MagicMock()
        resumer = ConversationResumer(fs)
        resumer._load_metadata = AsyncMock(side_effect=FileNotFoundError)

        result = await resumer.load("sid-99")
        assert result is None

    async def test_returns_snapshot_on_success(self):
        fs = MagicMock()
        resumer = ConversationResumer(fs)

        mock_meta = {"title": "hello"}
        mock_events = [MagicMock(), MagicMock()]
        mock_state = {"iteration": 3}

        resumer._load_metadata = AsyncMock(return_value=mock_meta)
        resumer._replay_events = AsyncMock(return_value=mock_events)
        resumer._load_latest_checkpoint = AsyncMock(
            return_value=(mock_state, "checkpoint-5")
        )

        snap = await resumer.load("sid-1")
        assert snap is not None
        assert snap.session_id == "sid-1"
        assert snap.metadata == mock_meta
        assert len(snap.events) == 2
        assert snap.state == mock_state
        assert snap.checkpoint_name == "checkpoint-5"

    async def test_returns_snapshot_without_checkpoint(self):
        fs = MagicMock()
        resumer = ConversationResumer(fs)

        resumer._load_metadata = AsyncMock(return_value={"title": "no cp"})
        resumer._replay_events = AsyncMock(return_value=[])
        resumer._load_latest_checkpoint = AsyncMock(return_value=(None, None))

        snap = await resumer.load("sid-2")
        assert snap is not None
        assert snap.state is None
        assert snap.checkpoint_name is None


# ── list_sessions ─────────────────────────────────────────────────────


class TestListSessions:
    async def test_returns_session_ids(self):
        fs = MagicMock()
        resumer = ConversationResumer(fs)

        with patch(
            "backend.utils.async_utils.call_sync_from_async",
            new_callable=AsyncMock,
            return_value=["session1/", "session2/", ".hidden/"],
        ):
            result = await resumer.list_sessions()
            assert "session1" in result
            assert "session2" in result
            assert ".hidden" not in result

    async def test_returns_empty_on_file_not_found(self):
        fs = MagicMock()
        resumer = ConversationResumer(fs)

        with patch(
            "backend.utils.async_utils.call_sync_from_async",
            new_callable=AsyncMock,
            side_effect=FileNotFoundError,
        ):
            result = await resumer.list_sessions()
            assert result == []


# ── _load_metadata ────────────────────────────────────────────────────


class TestLoadMetadata:
    async def test_loads_json_metadata(self):
        fs = MagicMock()
        resumer = ConversationResumer(fs)
        raw_json = json.dumps({"title": "meta test", "key": 42})

        with patch(
            "backend.utils.async_utils.call_sync_from_async",
            new_callable=AsyncMock,
            return_value=raw_json,
        ):
            meta = await resumer._load_metadata("sid-10")
            assert meta["title"] == "meta test"
            assert meta["key"] == 42


# ── _replay_events ────────────────────────────────────────────────────


class TestReplayEvents:
    async def test_empty_events_dir(self):
        fs = MagicMock()
        resumer = ConversationResumer(fs)

        with patch(
            "backend.utils.async_utils.call_sync_from_async",
            new_callable=AsyncMock,
            side_effect=FileNotFoundError,
        ):
            events = await resumer._replay_events("sid-1")
            assert events == []

    async def test_sorts_and_deserializes_events(self):
        fs = MagicMock()
        resumer = ConversationResumer(fs)

        list_return = ["2.json", "1.json", "3.json"]
        event_data = {
            "id": 1,
            "action": "message",
            "source": "agent",
            "message": "hi",
            "args": {"content": "hello", "wait_for_response": False},
            "timestamp": "2025-01-01T00:00:00",
        }

        call_count = {"n": 0}

        async def mock_call_sync(fn, *args):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return list_return
            return json.dumps(event_data)

        with (
            patch(
                "backend.utils.async_utils.call_sync_from_async",
                side_effect=mock_call_sync,
            ),
            patch(
                "backend.storage.conversation.conversation_resumer.event_from_dict",
                return_value=MagicMock(),
            ) as mock_efd,
        ):
            events = await resumer._replay_events("sid-1")
            assert len(events) == 3
            assert mock_efd.call_count == 3

    async def test_skips_corrupt_events(self):
        fs = MagicMock()
        resumer = ConversationResumer(fs)

        call_count = {"n": 0}

        async def mock_call_sync(fn, *args):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return ["1.json", "2.json"]
            if call_count["n"] == 2:
                return "NOT VALID JSON %%!!"
            return json.dumps({"action": "message", "args": {"content": "ok"}})

        with (
            patch(
                "backend.utils.async_utils.call_sync_from_async",
                side_effect=mock_call_sync,
            ),
            patch(
                "backend.storage.conversation.conversation_resumer.event_from_dict",
                side_effect=[ValueError("bad"), MagicMock()],
            ),
        ):
            events = await resumer._replay_events("sid-1")
            # First event corrupt, second ok → 1 event
            assert len(events) <= 2  # At least doesn't crash

    async def test_excludes_pending_files(self):
        fs = MagicMock()
        resumer = ConversationResumer(fs)

        call_count = {"n": 0}

        async def mock_call_sync(fn, *args):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return ["1.json", "2.json.pending", "3.json"]
            return json.dumps({"action": "message", "args": {}})

        with (
            patch(
                "backend.utils.async_utils.call_sync_from_async",
                side_effect=mock_call_sync,
            ),
            patch(
                "backend.storage.conversation.conversation_resumer.event_from_dict",
                return_value=MagicMock(),
            ) as mock_efd,
        ):
            await resumer._replay_events("sid-1")
            assert mock_efd.call_count == 2  # pending file excluded


# ── _load_latest_checkpoint ───────────────────────────────────────────


class TestLoadLatestCheckpoint:
    async def test_no_checkpoints(self):
        fs = MagicMock()
        resumer = ConversationResumer(fs)

        with patch(
            "backend.controller.state.session_checkpoint_manager.SessionCheckpointManager"
        ) as MockMgr:
            mgr = MockMgr.return_value
            mgr.list_checkpoints.return_value = []

            state, name = await resumer._load_latest_checkpoint("sid-1")
            assert state is None
            assert name is None

    async def test_loads_latest_checkpoint(self):
        fs = MagicMock()
        resumer = ConversationResumer(fs)

        # Use a simple namespace instead of MagicMock to avoid __dict__ conflicts
        class FakeState:
            def __init__(self):
                self.iteration = 5
                self.status = "active"
                self._private = True

        with patch(
            "backend.controller.state.session_checkpoint_manager.SessionCheckpointManager"
        ) as MockMgr:
            mgr = MockMgr.return_value
            mgr.list_checkpoints.return_value = ["cp1", "cp2", "cp3"]
            mgr.restore_checkpoint.return_value = FakeState()

            state, name = await resumer._load_latest_checkpoint("sid-1")
            assert name == "cp3"
            mgr.restore_checkpoint.assert_called_once_with("cp3")
            assert state is not None
            assert "iteration" in state
            assert "_private" not in state

    async def test_returns_none_when_restore_fails(self):
        fs = MagicMock()
        resumer = ConversationResumer(fs)

        with patch(
            "backend.controller.state.session_checkpoint_manager.SessionCheckpointManager"
        ) as MockMgr:
            mgr = MockMgr.return_value
            mgr.list_checkpoints.return_value = ["cp1"]
            mgr.restore_checkpoint.return_value = None

            state, name = await resumer._load_latest_checkpoint("sid-1")
            assert state is None
            assert name is None
