"""Tests for backend.ledger.adapter — EventServiceAdapter."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from backend.ledger.adapter import EventServiceAdapter


@pytest.fixture()
def file_store_factory():
    return MagicMock(return_value=MagicMock())


@pytest.fixture(autouse=True)
def cleanup_adapter_streams():
    """Automatically close any streams created by test adapters to prevent GC resource leak warnings."""
    adapters = []

    # We patch __init__ so we can track all adapter instances created in the test
    original_init = EventServiceAdapter.__init__

    def wrapped_init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        adapters.append(self)

    EventServiceAdapter.__init__ = wrapped_init  # type: ignore
    yield
    EventServiceAdapter.__init__ = original_init  # type: ignore
    for adapter in adapters:
        for stream in adapter._streams.values():
            stream.close()


class TestEventServiceAdapterInit:
    def test_basic_init(self, file_store_factory):
        adapter = EventServiceAdapter(file_store_factory=file_store_factory)
        assert adapter._sessions == {}
        assert adapter._streams == {}

    def test_grpc_raises(self, file_store_factory):
        with pytest.raises(RuntimeError, match='gRPC mode is not available'):
            EventServiceAdapter(file_store_factory=file_store_factory, use_grpc=True)


class TestStartSession:
    def test_auto_generates_session_id(self, file_store_factory):
        adapter = EventServiceAdapter(file_store_factory=file_store_factory)
        info = adapter.start_session()
        assert 'session_id' in info
        assert info['session_id']  # not empty

    def test_custom_session_id(self, file_store_factory):
        adapter = EventServiceAdapter(file_store_factory=file_store_factory)
        info = adapter.start_session(session_id='my-session')
        assert info['session_id'] == 'my-session'

    def test_stores_metadata(self, file_store_factory):
        adapter = EventServiceAdapter(file_store_factory=file_store_factory)
        info = adapter.start_session(
            session_id='s1',
            user_id='u1',
            repository='repo',
            branch='main',
            labels={'env': 'test'},
        )
        assert info['user_id'] == 'u1'
        assert info['repository'] == 'repo'
        assert info['branch'] == 'main'
        assert info['labels'] == {'env': 'test'}

    def test_creates_event_stream(self, file_store_factory):
        adapter = EventServiceAdapter(file_store_factory=file_store_factory)
        adapter.start_session(session_id='s1', user_id='u1')
        assert 's1' in adapter._streams
        file_store_factory.assert_called_with('u1')

    def test_default_labels_empty(self, file_store_factory):
        adapter = EventServiceAdapter(file_store_factory=file_store_factory)
        info = adapter.start_session(session_id='s2')
        assert info['labels'] == {}


class TestGetEventStream:
    def test_returns_stream_after_start(self, file_store_factory):
        adapter = EventServiceAdapter(file_store_factory=file_store_factory)
        adapter.start_session(session_id='s1')
        stream = adapter.get_event_stream('s1')
        assert stream is not None

    def test_unknown_session_raises(self, file_store_factory):
        adapter = EventServiceAdapter(file_store_factory=file_store_factory)
        with pytest.raises(ValueError, match='not found'):
            adapter.get_event_stream('nonexistent')

    def test_recovery_from_session_info(self, file_store_factory):
        """If stream is missing but session_info exists, it creates a new stream."""
        adapter = EventServiceAdapter(file_store_factory=file_store_factory)
        adapter.start_session(session_id='s1', user_id='u1')
        # Remove stream but keep session info
        adapter._streams['s1'].close()
        del adapter._streams['s1']
        stream = adapter.get_event_stream('s1')
        assert stream is not None


class TestGetSessionInfo:
    def test_returns_info(self, file_store_factory):
        adapter = EventServiceAdapter(file_store_factory=file_store_factory)
        adapter.start_session(session_id='s1', user_id='u1')
        info = adapter.get_session_info('s1')
        assert info is not None
        assert info['session_id'] == 's1'

    def test_returns_none_for_unknown(self, file_store_factory):
        adapter = EventServiceAdapter(file_store_factory=file_store_factory)
        assert adapter.get_session_info('unknown') is None
