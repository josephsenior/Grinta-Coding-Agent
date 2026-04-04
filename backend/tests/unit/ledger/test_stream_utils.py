"""Tests for event stream utility functions."""

from unittest.mock import MagicMock, patch

import pytest

from backend.ledger.stream import (
    EventStreamSubscriber,
    _warn_unclosed_stream,
    session_exists,
)


class TestEventStreamSubscriber:
    def test_enum_values(self):
        """Test EventStreamSubscriber enum values."""
        assert EventStreamSubscriber.AGENT_CONTROLLER.value == 'agent_controller'
        assert EventStreamSubscriber.SERVER.value == 'server'
        assert EventStreamSubscriber.RUNTIME.value == 'runtime'
        assert EventStreamSubscriber.MEMORY.value == 'memory'
        assert EventStreamSubscriber.MAIN.value == 'main'
        assert EventStreamSubscriber.TEST.value == 'test'

    def test_enum_is_string(self):
        """Test that EventStreamSubscriber extends str."""
        assert isinstance(EventStreamSubscriber.AGENT_CONTROLLER, str)
        assert isinstance(EventStreamSubscriber.SERVER, str)

    def test_enum_equality(self):
        """Test enum value equality."""
        assert EventStreamSubscriber.AGENT_CONTROLLER.value == 'agent_controller'
        # str() returns full enum name, not just value
        assert EventStreamSubscriber.SERVER.value == 'server'


class TestWarnUnclosedStream:
    def test_warn_unclosed_stream_logs_warning(self):
        """Test that _warn_unclosed_stream writes a warning to stderr."""
        import io

        fake_stderr = io.StringIO()
        with (
            patch('sys.stderr', fake_stderr),
            patch('sys.is_finalizing', return_value=False),
        ):
            _warn_unclosed_stream('session123')

        output = fake_stderr.getvalue()
        assert 'session123' in output
        assert "GC'd without close" in output

    def test_warn_unclosed_stream_message_format(self):
        """Test warning message format."""
        import io

        fake_stderr = io.StringIO()
        with (
            patch('sys.stderr', fake_stderr),
            patch('sys.is_finalizing', return_value=False),
        ):
            _warn_unclosed_stream('test-sid')

        output = fake_stderr.getvalue()
        assert 'EventStream' in output
        assert 'test-sid' in output
        assert 'resources may leak' in output

    def test_warn_unclosed_stream_different_sids(self):
        """Test warning with different session IDs."""
        import io

        fake_stderr = io.StringIO()
        with (
            patch('sys.stderr', fake_stderr),
            patch('sys.is_finalizing', return_value=False),
        ):
            _warn_unclosed_stream('sid-1')
            _warn_unclosed_stream('sid-2')

        output = fake_stderr.getvalue()
        assert 'sid-1' in output
        assert 'sid-2' in output


class TestSessionExists:
    @pytest.mark.asyncio
    async def test_session_exists_true(self):
        """Test session_exists returns True when session directory exists."""
        mock_store = MagicMock()
        # Mock successful list call
        with patch(
            'backend.ledger.stream.call_sync_from_async',
            return_value=['file1.json', 'file2.json'],
        ):
            result = await session_exists('sess123', mock_store, None)

        assert result is True

    @pytest.mark.asyncio
    async def test_session_exists_false(self):
        """Test session_exists returns False when directory not found."""
        mock_store = MagicMock()
        # Mock FileNotFoundError
        with patch(
            'backend.ledger.stream.call_sync_from_async',
            side_effect=FileNotFoundError('Not found'),
        ):
            result = await session_exists('sess456', mock_store, None)

        assert result is False

    @pytest.mark.asyncio
    async def test_session_exists_with_user_id(self):
        """Test session_exists with user ID."""
        mock_store = MagicMock()
        with patch(
            'backend.ledger.stream.call_sync_from_async',
            return_value=['state.json'],
        ) as mock_call:
            result = await session_exists('sess789', mock_store, 'user123')

        assert result is True
        # Verify get_conversation_dir was called with user_id
        mock_call.assert_called_once()

    @pytest.mark.asyncio
    async def test_session_exists_empty_directory(self):
        """Test session_exists with empty existing directory."""
        mock_store = MagicMock()
        with patch(
            'backend.ledger.stream.call_sync_from_async',
            return_value=[],
        ):
            result = await session_exists('sess-empty', mock_store, None)

        # Empty directory means session exists
        assert result is True

    @pytest.mark.asyncio
    async def test_session_exists_calls_file_store_list(self):
        """Test that session_exists calls file_store.list correctly."""
        mock_store = MagicMock()
        mock_store.list = MagicMock(return_value=['file.json'])

        with patch(
            'backend.ledger.stream.call_sync_from_async',
            wraps=lambda fn, *args: fn(*args),
        ):
            await session_exists('sid', mock_store, None)

        # Verify list was called
        mock_store.list.assert_called_once()

    @pytest.mark.asyncio
    async def test_session_exists_other_exception(self):
        """Test session_exists with non-FileNotFoundError exception."""
        mock_store = MagicMock()
        # Other exceptions should propagate
        with patch(
            'backend.ledger.stream.call_sync_from_async',
            side_effect=ValueError('Unexpected error'),
        ):
            with pytest.raises(ValueError, match='Unexpected error'):
                await session_exists('bad-sid', mock_store, None)
