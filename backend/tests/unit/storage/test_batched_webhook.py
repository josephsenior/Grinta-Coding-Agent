"""Tests for backend.storage.batched_web_hook — BatchedWebHookFileStore."""

from __future__ import annotations

from unittest.mock import MagicMock, patch


from backend.storage.batched_web_hook import (
    BatchedWebHookFileStore,
    WEBHOOK_BATCH_SIZE_LIMIT_BYTES,
    WEBHOOK_BATCH_TIMEOUT_SECONDS,
)


def _make_store(
    batch_timeout: float = 10.0,
    batch_size_limit: int = 1048576,
) -> tuple[BatchedWebHookFileStore, MagicMock, MagicMock]:
    """Create a BatchedWebHookFileStore with mocked dependencies."""
    inner_fs = MagicMock()
    inner_fs.read.return_value = "contents"
    inner_fs.list.return_value = ["file1.txt"]
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_client.post.return_value = mock_response

    store = BatchedWebHookFileStore(
        file_store=inner_fs,
        base_url="http://localhost:8080/webhook",
        client=mock_client,
        batch_timeout_seconds=batch_timeout,
        batch_size_limit_bytes=batch_size_limit,
    )
    return store, inner_fs, mock_client


# ===================================================================
# Initialization
# ===================================================================

class TestBatchedWebHookInit:

    def test_defaults(self):
        inner = MagicMock()
        store = BatchedWebHookFileStore(
            file_store=inner,
            base_url="http://example.com",
        )
        assert store.batch_timeout_seconds == WEBHOOK_BATCH_TIMEOUT_SECONDS
        assert store.batch_size_limit_bytes == WEBHOOK_BATCH_SIZE_LIMIT_BYTES

    def test_custom_params(self):
        inner = MagicMock()
        store = BatchedWebHookFileStore(
            file_store=inner,
            base_url="http://example.com",
            batch_timeout_seconds=1.0,
            batch_size_limit_bytes=512,
        )
        assert store.batch_timeout_seconds == 1.0
        assert store.batch_size_limit_bytes == 512


# ===================================================================
# Delegation to inner file store
# ===================================================================

class TestDelegation:

    def test_write_delegates(self):
        store, inner, _ = _make_store()
        store.write("path/to/file", "hello")
        inner.write.assert_called_once_with("path/to/file", "hello")

    def test_read_delegates(self):
        store, inner, _ = _make_store()
        result = store.read("path/to/file")
        inner.read.assert_called_once_with("path/to/file")
        assert result == "contents"

    def test_list_delegates(self):
        store, inner, _ = _make_store()
        result = store.list("dir/")
        inner.list.assert_called_once_with("dir/")
        assert result == ["file1.txt"]

    def test_delete_delegates(self):
        store, inner, _ = _make_store()
        store.delete("path/to/file")
        inner.delete.assert_called_once_with("path/to/file")


# ===================================================================
# Batching behavior
# ===================================================================

class TestBatching:

    def test_write_queues_update(self):
        store, _, _ = _make_store()
        store.write("a.txt", "data")
        assert "a.txt" in store._batch
        assert store._batch["a.txt"] == ("write", "data")

    def test_delete_queues_update(self):
        store, _, _ = _make_store()
        store.delete("a.txt")
        assert "a.txt" in store._batch
        assert store._batch["a.txt"] == ("delete", None)

    def test_overwrite_replaces_in_batch(self):
        store, _, _ = _make_store()
        store.write("a.txt", "v1")
        store.write("a.txt", "v2")
        assert store._batch["a.txt"] == ("write", "v2")

    def test_batch_size_tracking(self):
        store, _, _ = _make_store()
        store.write("a.txt", "12345")
        assert store._batch_size == 5

    def test_overwrite_adjusts_batch_size(self):
        store, _, _ = _make_store()
        store.write("a.txt", "123")  # 3 bytes
        store.write("a.txt", "12345")  # Replace with 5 bytes
        assert store._batch_size == 5


# ===================================================================
# Flush
# ===================================================================

class TestFlush:

    def test_flush_sends_batch(self):
        store, _, mock_client = _make_store()
        store.write("a.txt", "hello")
        store.flush()
        mock_client.post.assert_called_once()
        payload = mock_client.post.call_args[1]["json"]
        assert len(payload) == 1
        assert payload[0]["method"] == "POST"
        assert payload[0]["path"] == "a.txt"
        assert payload[0]["content"] == "hello"

    def test_flush_clears_batch(self):
        store, _, _ = _make_store()
        store.write("a.txt", "hello")
        store.flush()
        assert store._batch == {}
        assert store._batch_size == 0

    def test_flush_empty_batch(self):
        store, _, mock_client = _make_store()
        store.flush()
        # No HTTP call if batch is empty
        mock_client.post.assert_not_called()

    def test_flush_delete_payload(self):
        store, _, mock_client = _make_store()
        store.delete("old.txt")
        store.flush()
        payload = mock_client.post.call_args[1]["json"]
        assert payload[0]["method"] == "DELETE"
        assert "content" not in payload[0]


# ===================================================================
# Size-triggered flush
# ===================================================================

class TestSizeTriggeredFlush:

    @patch("backend.storage.batched_web_hook.EXECUTOR")
    def test_exceeds_size_limit_triggers_send(self, mock_executor):
        store, _, _ = _make_store(batch_size_limit=10)
        # Write data that exceeds the 10-byte limit
        store.write("big.txt", "a" * 20)
        # Should have submitted to executor
        mock_executor.submit.assert_called()


# ===================================================================
# Timer management
# ===================================================================

class TestTimerManagement:

    def test_timer_created_on_write(self):
        store, _, _ = _make_store(batch_timeout=100)
        store.write("a.txt", "data")
        assert store._batch_timer is not None

    def test_timer_cancelled_on_new_write(self):
        store, _, _ = _make_store(batch_timeout=100)
        store.write("a.txt", "data")
        first_timer = store._batch_timer
        store.write("b.txt", "data")
        # First timer should have been cancelled
        assert store._batch_timer is not first_timer

    def test_timer_cleared_after_flush(self):
        store, _, _ = _make_store()
        store.write("a.txt", "data")
        store.flush()
        assert store._batch_timer is None


# ===================================================================
# Bytes handling in payload
# ===================================================================

class TestBytesHandling:

    def test_bytes_content_utf8(self):
        store, inner, mock_client = _make_store()
        store.write("file.txt", b"hello bytes")
        store.flush()
        payload = mock_client.post.call_args[1]["json"]
        assert payload[0]["content"] == "hello bytes"

    def test_bytes_content_base64_fallback(self):
        store, inner, mock_client = _make_store()
        # Non-UTF-8 bytes
        store.write("file.bin", b"\xff\xfe\xfd")
        store.flush()
        payload = mock_client.post.call_args[1]["json"]
        assert payload[0]["encoding"] == "base64"
