"""Tests for backend.storage.base_web_hook — BaseWebHookFileStore."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from backend.storage.base_web_hook import BaseWebHookFileStore


@pytest.fixture()
def inner_store():
    return MagicMock()


@pytest.fixture()
def hook_store(inner_store):
    client = MagicMock()
    return BaseWebHookFileStore(file_store=inner_store, base_url="http://hook.test/", client=client)


class TestBaseWebHookInit:
    def test_stores_fields(self, inner_store):
        client = MagicMock()
        s = BaseWebHookFileStore(inner_store, "http://example.com/", client)
        assert s.file_store is inner_store
        assert s.base_url == "http://example.com/"
        assert s.client is client

    def test_default_client(self, inner_store):
        """If no client is given, a new httpx.Client is created."""
        s = BaseWebHookFileStore(inner_store, "http://test.com/")
        assert s.client is not None


class TestBaseWebHookRead:
    def test_delegates_read(self, hook_store, inner_store):
        inner_store.read.return_value = "content"
        result = hook_store.read("file.txt")
        inner_store.read.assert_called_once_with("file.txt")
        assert result == "content"


class TestBaseWebHookList:
    def test_delegates_list(self, hook_store, inner_store):
        inner_store.list.return_value = ["a.txt", "b/"]
        result = hook_store.list("dir")
        inner_store.list.assert_called_once_with("dir")
        assert result == ["a.txt", "b/"]


class TestBaseWebHookDelete:
    def test_delegates_delete(self, hook_store, inner_store):
        hook_store.delete("path/to/file")
        inner_store.delete.assert_called_once_with("path/to/file")
