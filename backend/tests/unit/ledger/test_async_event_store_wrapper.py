"""Tests for backend.ledger.async_event_store_wrapper — AsyncEventStoreWrapper."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from backend.ledger.async_event_store_wrapper import AsyncEventStoreWrapper
from backend.ledger.event import Event


class TestAsyncEventStoreWrapper:
    def _make_event(self, content: str = 'test') -> Event:
        """Create a minimal mock event."""
        ev = MagicMock(spec=Event)
        ev.content = content
        return ev

    @pytest.mark.asyncio
    async def test_empty_store(self):
        store = MagicMock()
        store.search_events.return_value = []
        wrapper = AsyncEventStoreWrapper(store)
        events = [e async for e in wrapper]
        assert events == []

    @pytest.mark.asyncio
    async def test_iterates_events(self):
        e1 = self._make_event('first')
        e2 = self._make_event('second')
        store = MagicMock()
        store.search_events.return_value = [e1, e2]
        wrapper = AsyncEventStoreWrapper(store)
        events = [e async for e in wrapper]
        assert len(events) == 2
        assert events[0] is e1
        assert events[1] is e2

    @pytest.mark.asyncio
    async def test_passes_args(self):
        store = MagicMock()
        store.search_events.return_value = []
        wrapper = AsyncEventStoreWrapper(store, 'arg1', 'arg2', key='val')
        _ = [e async for e in wrapper]
        store.search_events.assert_called_once_with('arg1', 'arg2', key='val')

    @pytest.mark.asyncio
    async def test_single_event(self):
        ev = self._make_event('only')
        store = MagicMock()
        store.search_events.return_value = [ev]
        wrapper = AsyncEventStoreWrapper(store)
        events = [e async for e in wrapper]
        assert len(events) == 1
        assert events[0] is ev

    @pytest.mark.asyncio
    async def test_preserves_event_identity(self):
        """Each yielded event should be the exact same object from search_events."""
        originals = [self._make_event(f'e{i}') for i in range(5)]
        store = MagicMock()
        store.search_events.return_value = originals
        wrapper = AsyncEventStoreWrapper(store)
        events = [e async for e in wrapper]
        for orig, yielded in zip(originals, events, strict=False):
            assert orig is yielded
