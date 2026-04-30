from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timedelta
from typing import Any

import pytest

from backend.persistence.conversation.file_conversation_store import (
    FileConversationStore,
    _sort_key,
)
from backend.persistence.data_models.conversation_metadata import ConversationMetadata


class _FS:
    def __init__(self) -> None:
        self.data: dict[str, str] = {}
        self.deleted: list[str] = []
        self.listing: dict[str, list[str]] = {}

    def write(self, path: str, content: str) -> None:
        self.data[path] = (
            content.decode('utf-8') if isinstance(content, bytes) else content
        )

    def read(self, path: str) -> str:
        if path not in self.data:
            raise FileNotFoundError(path)
        return self.data[path]

    def delete(self, path: str) -> None:
        self.deleted.append(path)

    def list(self, path: str) -> list[str]:
        if path not in self.listing:
            raise FileNotFoundError(path)
        return self.listing[path]


def _metadata(cid: str, title: str = 'T') -> ConversationMetadata:
    return ConversationMetadata(
        conversation_id=cid,
        title=title,
        selected_repository=None,
        created_at=datetime.now(),
        user_id='u1',
    )


@pytest.mark.asyncio
async def test_save_and_get_metadata_roundtrip() -> None:
    fs = _FS()
    store = FileConversationStore(file_store=fs, config=None, user_id='u1')
    meta = _metadata('c1', 'Title1')

    await store.save_metadata(meta)
    got = await store.get_metadata('c1')

    assert got.conversation_id == 'c1'
    assert got.title == 'Title1'


@pytest.mark.asyncio
async def test_get_metadata_creates_default_on_missing() -> None:
    fs = _FS()
    store = FileConversationStore(file_store=fs, config=None, user_id='u1')
    got = await store.get_metadata('missing-id')
    assert got.conversation_id == 'missing-id'
    assert got.title == 'New Conversation'


@pytest.mark.asyncio
async def test_get_metadata_raises_when_missing_and_create_false() -> None:
    fs = _FS()
    store = FileConversationStore(file_store=fs, config=None, user_id='u1')
    with pytest.raises(FileNotFoundError):
        await store.get_metadata('missing-id', create_if_missing=False)


@pytest.mark.asyncio
async def test_get_metadata_removes_legacy_github_user_id_field() -> None:
    fs = _FS()
    store = FileConversationStore(file_store=fs, config=None, user_id='u1')
    path = store.get_conversation_metadata_filename('legacy')
    payload: dict[str, Any] = asdict(_metadata('legacy', 'Legacy'))
    payload['github_user_id'] = 'old-field'
    fs.data[path] = json.dumps(payload, default=str)

    got = await store.get_metadata('legacy')
    assert got.conversation_id == 'legacy'
    assert got.title == 'Legacy'


@pytest.mark.asyncio
async def test_delete_and_exists_and_delete_all() -> None:
    fs = _FS()
    store = FileConversationStore(file_store=fs, config=None, user_id='u1')
    path = store.get_conversation_metadata_filename('c2')
    fs.data[path] = json.dumps(asdict(_metadata('c2')), default=str)

    assert await store.exists('c2') is True
    assert await store.exists('does-not-exist') is False

    await store.delete_metadata('c2')
    assert fs.deleted

    metadata_dir = store.get_conversation_metadata_dir()
    fs.listing[metadata_dir] = ['a/.hidden', 'a/c3', 'a/c4']
    await store.delete_all_metadata()
    assert len(fs.deleted) >= 2


@pytest.mark.asyncio
async def test_search_sorts_and_paginates() -> None:
    fs = _FS()
    store = FileConversationStore(file_store=fs, config=None, user_id='u1')
    metadata_dir = store.get_conversation_metadata_dir()
    fs.listing[metadata_dir] = ['x/c1', 'x/c2', 'x/c3']

    now = datetime.now()
    values = {
        'c1': _metadata('c1', 'A'),
        'c2': _metadata('c2', 'B'),
        'c3': _metadata('c3', 'C'),
    }
    values['c1'].created_at = now - timedelta(days=3)
    values['c2'].created_at = now - timedelta(days=1)
    values['c3'].created_at = now - timedelta(days=2)
    for cid, m in values.items():
        fs.data[store.get_conversation_metadata_filename(cid)] = json.dumps(
            asdict(m), default=str
        )

    result = await store.search(limit=2)
    ids = [c.conversation_id for c in result.results]
    assert ids == ['c2', 'c3']
    assert result.next_page_id is not None


def test_sort_key_handles_missing_created_at() -> None:
    meta = _metadata('c10')
    meta.created_at = None  # type: ignore[assignment]
    assert _sort_key(meta) == ''
