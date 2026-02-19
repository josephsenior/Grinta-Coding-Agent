"""Tests for backend.events.persistence — EventPersistence with file-store mocks."""

from __future__ import annotations

from unittest.mock import MagicMock, patch


from backend.events.persistence import EventPersistence, _truncate_payload


# ── Helper to build a persistence instance with file-store mock ───────


def _make_persistence(**overrides) -> tuple[EventPersistence, MagicMock]:
    file_store = MagicMock()
    defaults = {
        "sid": "test-session",
        "file_store": file_store,
        "user_id": None,
        "async_write": False,
        "get_filename_for_id": lambda eid, uid: f"events/{eid}.json",
        "get_filename_for_cache": lambda s, e: f"cache/{s}_{e}.json",
        "cache_size": 3,
    }
    defaults.update(overrides)
    with patch.dict("os.environ", {"FORGE_SQLITE_EVENTS": "false"}):
        p = EventPersistence(**defaults)
    return p, file_store


# ── is_critical_event / is_critical_payload ───────────────────────────


class TestIsCriticalEventPersist:
    def test_critical_action(self):
        event = MagicMock(action="finish", observation=None)
        assert EventPersistence.is_critical_event(event) is True

    def test_critical_observation(self):
        event = MagicMock(action=None, observation="error")
        assert EventPersistence.is_critical_event(event) is True

    def test_non_critical(self):
        event = MagicMock(action="run", observation=None)
        assert EventPersistence.is_critical_event(event) is False

    def test_no_action_or_observation(self):
        event = MagicMock(spec=[])
        assert EventPersistence.is_critical_event(event) is False

    def test_critical_payload(self):
        assert EventPersistence.is_critical_payload({"action": "finish"}) is True
        assert EventPersistence.is_critical_payload({"observation": "error"}) is True
        assert EventPersistence.is_critical_payload({"action": "run"}) is False
        assert EventPersistence.is_critical_payload({}) is False


# ── persist_event (sync path) ─────────────────────────────────────────


class TestPersistSyncPath:
    def test_writes_with_wal_markers(self):
        p, fs = _make_persistence()
        payload = {"id": 1, "action": "run"}
        p.persist_event(payload, event_id=1, cache_payload=None)

        calls = fs.write.call_args_list
        assert any("pending" in str(c) for c in calls)
        assert any("events/1.json" in str(c) for c in calls)
        fs.delete.assert_called_once()

    def test_critical_event_always_sync(self):
        p, fs = _make_persistence()
        payload = {"id": 2, "action": "finish"}
        p.persist_event(payload, event_id=2, cache_payload=None)
        assert p.stats["critical_sync_persistence"] == 1

    def test_writes_cache_payload(self):
        p, fs = _make_persistence()
        payload = {"id": 3, "action": "run"}
        cache = ("cache/0_3.json", '[{"id":0},{"id":1},{"id":2}]')
        p.persist_event(payload, event_id=3, cache_payload=cache)

        write_calls = [str(c) for c in fs.write.call_args_list]
        assert any("cache/0_3.json" in w for w in write_calls)


# ── build_cache_payload ───────────────────────────────────────────────


class TestBuildCachePayloadPersist:
    def test_returns_none_when_not_full(self):
        p, _ = _make_persistence(cache_size=3)
        page = [{"id": 0}, {"id": 1}]
        assert p.build_cache_payload(page) is None

    def test_returns_payload_when_full(self):
        p, _ = _make_persistence(cache_size=3)
        page = [{"id": 0}, {"id": 1}, {"id": 2}]
        result = p.build_cache_payload(page)
        assert result is not None
        filename, contents = result
        assert "cache/" in filename

    def test_returns_none_for_empty(self):
        p, _ = _make_persistence()
        assert p.build_cache_payload(None) is None
        assert p.build_cache_payload([]) is None


# ── _normalize_event_path ─────────────────────────────────────────────


class TestNormalizeEventPathPersist:
    def test_adds_prefix_when_missing(self):
        result = EventPersistence._normalize_event_path("5.json.pending", "events/dir/")
        assert result == "events/dir/5.json.pending"

    def test_preserves_existing_prefix(self):
        result = EventPersistence._normalize_event_path(
            "events/dir/5.json.pending", "events/dir/"
        )
        assert result == "events/dir/5.json.pending"

    def test_normalizes_backslashes(self):
        result = EventPersistence._normalize_event_path(
            "events\\dir\\5.json", "events/dir/"
        )
        assert result == "events/dir/5.json"


# ── replay_pending_events ─────────────────────────────────────────────


class TestReplayPendingEventsPersist:
    def test_no_pending_files_is_noop(self):
        p, fs = _make_persistence()
        fs.list.return_value = ["1.json", "2.json"]
        p.replay_pending_events()
        fs.read.assert_not_called()

    def test_stale_marker_cleaned_up(self):
        p, fs = _make_persistence()
        fs.list.return_value = ["1.json.pending"]
        fs.read.side_effect = lambda path: '{"id":1}'
        p.replay_pending_events()
        fs.delete.assert_called()

    def test_recovers_missing_event(self):
        p, fs = _make_persistence()
        fs.list.return_value = ["1.json.pending"]

        def _read_side_effect(path):
            if path.endswith(".pending"):
                return '{"id": 1}'
            raise FileNotFoundError

        fs.read.side_effect = _read_side_effect
        p.replay_pending_events()
        assert fs.write.called
        assert fs.delete.called

    def test_events_dir_not_found(self):
        p, fs = _make_persistence()
        fs.list.side_effect = FileNotFoundError
        p.replay_pending_events()  # Should not raise


# ── close ─────────────────────────────────────────────────────────────


class TestClosePersist:
    def test_close_without_durable_writer(self):
        p, _ = _make_persistence()
        p.close()

    def test_close_stops_durable_writer(self):
        p, _ = _make_persistence()
        p._durable_writer = MagicMock()
        p.close()
        p._durable_writer.stop.assert_called_once()


# ── _truncate_payload ─────────────────────────────────────────────────


class TestTruncatePayloadPersist:
    def test_truncates_large_string_field(self):
        big_value = "x" * 100_000
        payload = {"content": big_value, "id": 1}
        _truncate_payload(payload, max_bytes=10_000)
        assert len(payload["content"]) < 100_000
        assert "truncated by Forge" in payload["content"]

    def test_leaves_small_payloads_untouched(self):
        payload = {"content": "small", "id": 1}
        _truncate_payload(payload, max_bytes=1_000_000)
        assert payload["content"] == "small"

    def test_handles_nested_dicts(self):
        big_value = "y" * 100_000
        payload = {"nested": {"content": big_value}, "id": 1}
        _truncate_payload(payload, max_bytes=10_000)
        assert len(payload["nested"]["content"]) < 100_000
