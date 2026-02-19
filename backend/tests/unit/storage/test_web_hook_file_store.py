"""Tests for backend.storage.web_hook — WebHookFileStore."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from backend.storage.web_hook import WebHookFileStore


@pytest.fixture()
def inner_store():
    return MagicMock()


@pytest.fixture()
def client():
    c = MagicMock()
    c.post.return_value = MagicMock(status_code=200)
    c.post.return_value.raise_for_status = MagicMock()
    c.delete.return_value = MagicMock(status_code=200)
    c.delete.return_value.raise_for_status = MagicMock()
    return c


@pytest.fixture()
def hook_store(inner_store, client):
    return WebHookFileStore(
        file_store=inner_store, base_url="http://hook.test/", client=client
    )


class TestWebHookWrite:
    @patch("backend.storage.web_hook.EXECUTOR")
    def test_write_delegates_to_inner(self, mock_executor, hook_store, inner_store):
        hook_store.write("file.txt", "data")
        inner_store.write.assert_called_once_with("file.txt", "data")

    @patch("backend.storage.web_hook.EXECUTOR")
    def test_write_submits_webhook(self, mock_executor, hook_store):
        hook_store.write("path.txt", "content")
        mock_executor.submit.assert_called_once()
        # First arg is the callback, next args are path, contents
        call_args = mock_executor.submit.call_args
        assert call_args[0][0] == hook_store._on_write


class TestWebHookDelete:
    @patch("backend.storage.web_hook.EXECUTOR")
    def test_delete_delegates_to_inner(self, mock_executor, hook_store, inner_store):
        hook_store.delete("file.txt")
        inner_store.delete.assert_called_once_with("file.txt")

    @patch("backend.storage.web_hook.EXECUTOR")
    def test_delete_submits_webhook(self, mock_executor, hook_store):
        hook_store.delete("path.txt")
        mock_executor.submit.assert_called_once()
        call_args = mock_executor.submit.call_args
        assert call_args[0][0] == hook_store._on_delete


class TestOnWrite:
    def test_posts_to_webhook(self, hook_store, client):
        hook_store._on_write("test.txt", "body")
        client.post.assert_called_once_with("http://hook.test/test.txt", content="body")
        client.post.return_value.raise_for_status.assert_called_once()

    def test_posts_bytes(self, hook_store, client):
        hook_store._on_write("b.bin", b"\x00\x01")
        client.post.assert_called_once_with(
            "http://hook.test/b.bin", content=b"\x00\x01"
        )


class TestOnDelete:
    def test_deletes_from_webhook(self, hook_store, client):
        hook_store._on_delete("rm.txt")
        client.delete.assert_called_once_with("http://hook.test/rm.txt")
        client.delete.return_value.raise_for_status.assert_called_once()
