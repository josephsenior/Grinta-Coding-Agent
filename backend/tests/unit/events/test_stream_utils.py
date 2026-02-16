"""Tests for event stream utility functions."""

from unittest.mock import MagicMock, patch

import pytest

from backend.events.stream import EventStreamSubscriber, _warn_unclosed_stream, session_exists


class TestEventStreamSubscriber:
    def test_enum_values(self):
        """Test EventStreamSubscriber enum values."""
        assert EventStreamSubscriber.AGENT_CONTROLLER == "agent_controller"
        assert EventStreamSubscriber.SERVER == "server"
        assert EventStreamSubscriber.RUNTIME == "runtime"
        assert EventStreamSubscriber.MEMORY == "memory"
        assert EventStreamSubscriber.MAIN == "main"
        assert EventStreamSubscriber.TEST == "test"

    def test_enum_is_string(self):
        """Test that EventStreamSubscriber extends str."""
        assert isinstance(EventStreamSubscriber.AGENT_CONTROLLER, str)
        assert isinstance(EventStreamSubscriber.SERVER, str)

    def test_enum_equality(self):
        """Test enum value equality."""
        assert EventStreamSubscriber.AGENT_CONTROLLER.value == "agent_controller"
        # str() returns full enum name, not just value
        assert EventStreamSubscriber.SERVER.value == "server"


class TestWarnUnclosedStream:
    @patch("backend.events.stream.logger")
    def test_warn_unclosed_stream_logs_warning(self, mock_logger):
        """Test that _warn_unclosed_stream logs a warning."""
        _warn_unclosed_stream("session123")

        mock_logger.warning.assert_called_once()
        # Logger uses %s formatting, so format string and args are separate
        call_args = mock_logger.warning.call_args[0]
        assert "%s" in call_args[0] or "session123" in str(call_args)
        assert "GC'd without close" in call_args[0]

    @patch("backend.events.stream.logger")
    def test_warn_unclosed_stream_message_format(self, mock_logger):
        """Test warning message format."""
        _warn_unclosed_stream("test-sid")

        mock_logger.warning.assert_called_once()
        message = mock_logger.warning.call_args[0][0]
        assert "EventStream" in message
        # test-sid is in args, not the format string
        assert "%s" in message
        assert "resources may leak" in message

    @patch("backend.events.stream.logger")
    def test_warn_unclosed_stream_different_sids(self, mock_logger):
        """Test warning with different session IDs."""
        _warn_unclosed_stream("sid-1")
        # sid-1 is in the args, not in format string
        assert mock_logger.warning.call_args[0][1] == "sid-1"

        mock_logger.reset_mock()

        _warn_unclosed_stream("sid-2")
        assert mock_logger.warning.call_args[0][1] == "sid-2"


class TestSessionExists:
    @pytest.mark.asyncio
    async def test_session_exists_true(self):
        """Test session_exists returns True when session directory exists."""
        mock_store = MagicMock()
        # Mock successful list call
        with patch(
            "backend.events.stream.call_sync_from_async",
            return_value=["file1.json", "file2.json"],
        ):
            result = await session_exists("sess123", mock_store, None)

        assert result is True

    @pytest.mark.asyncio
    async def test_session_exists_false(self):
        """Test session_exists returns False when directory not found."""
        mock_store = MagicMock()
        # Mock FileNotFoundError
        with patch(
            "backend.events.stream.call_sync_from_async",
            side_effect=FileNotFoundError("Not found"),
        ):
            result = await session_exists("sess456", mock_store, None)

        assert result is False

    @pytest.mark.asyncio
    async def test_session_exists_with_user_id(self):
        """Test session_exists with user ID."""
        mock_store = MagicMock()
        with patch(
            "backend.events.stream.call_sync_from_async",
            return_value=["state.json"],
        ) as mock_call:
            result = await session_exists("sess789", mock_store, "user123")

        assert result is True
        # Verify get_conversation_dir was called with user_id
        mock_call.assert_called_once()

    @pytest.mark.asyncio
    async def test_session_exists_empty_directory(self):
        """Test session_exists with empty existing directory."""
        mock_store = MagicMock()
        with patch(
            "backend.events.stream.call_sync_from_async",
            return_value=[],
        ):
            result = await session_exists("sess-empty", mock_store, None)

        # Empty directory means session exists
        assert result is True

    @pytest.mark.asyncio
    async def test_session_exists_calls_file_store_list(self):
        """Test that session_exists calls file_store.list correctly."""
        mock_store = MagicMock()
        mock_store.list = MagicMock(return_value=["file.json"])

        with patch(
            "backend.events.stream.call_sync_from_async",
            wraps=lambda fn, *args: fn(*args),
        ):
            await session_exists("sid", mock_store, None)

        # Verify list was called
        mock_store.list.assert_called_once()

    @pytest.mark.asyncio
    async def test_session_exists_other_exception(self):
        """Test session_exists with non-FileNotFoundError exception."""
        mock_store = MagicMock()
        # Other exceptions should propagate
        with patch(
            "backend.events.stream.call_sync_from_async",
            side_effect=ValueError("Unexpected error"),
        ):
            with pytest.raises(ValueError, match="Unexpected error"):
                await session_exists("bad-sid", mock_store, None)
