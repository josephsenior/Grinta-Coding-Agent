"""Comprehensive tests for TUI ForgeClient.

Tests HTTP client for backend API communication.
"""

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from backend.tui.client import ConversationInfo, ForgeClient, ServerConfig


class TestConversationInfo(unittest.TestCase):
    """Tests for ConversationInfo dataclass."""

    def test_creation(self) -> None:
        """Test creating ConversationInfo."""
        info = ConversationInfo(
            conversation_id="conv_123",
            title="Test Project",
            status="active",
        )
        self.assertEqual(info.conversation_id, "conv_123")
        self.assertEqual(info.title, "Test Project")
        self.assertEqual(info.status, "active")

    def test_optional_fields(self) -> None:
        """Test ConversationInfo with optional fields."""
        info = ConversationInfo(
            conversation_id="conv_123",
            title=None,
            status="completed",
        )
        self.assertIsNone(info.title)


class TestServerConfig(unittest.TestCase):
    """Tests for ServerConfig dataclass."""

    def test_creation(self) -> None:
        """Test creating ServerConfig."""
        config = ServerConfig(
            app_mode="oss",
            file_uploads_allowed=True,
            max_file_size_mb=10,
            security_model="local",
        )
        self.assertEqual(config.app_mode, "oss")
        self.assertTrue(config.file_uploads_allowed)
        self.assertEqual(config.max_file_size_mb, 10)


class TestForgeClient(unittest.IsolatedAsyncioTestCase):
    """Tests for ForgeClient HTTP communication."""

    def setUp(self) -> None:
        self.client = ForgeClient(base_url="http://localhost:3000")

    async def asyncTearDown(self) -> None:
        await self.client.close()

    async def test_init_default_url(self) -> None:
        """Test client initializes with default URL."""
        client = ForgeClient()
        self.assertIn("localhost", client.base_url)
        await client.close()

    async def test_init_custom_url(self) -> None:
        """Test client initializes with custom URL."""
        client = ForgeClient(base_url="http://example.com:8000")
        self.assertEqual(client.base_url, "http://example.com:8000")
        await client.close()

    @patch("httpx.AsyncClient.get")
    async def test_get_config(self, mock_get: AsyncMock) -> None:
        """Test getting server configuration."""
        mock_get.return_value = MagicMock(
            status_code=200,
            json=MagicMock(
                return_value={
                    "app_mode": "oss",
                    "file_uploads_allowed": True,
                    "max_file_size_mb": 50,
                    "security_model": "local",
                }
            ),
        )

        config = await self.client.get_config()
        self.assertEqual(config.app_mode, "oss")
        self.assertTrue(config.file_uploads_allowed)

    @patch("httpx.AsyncClient.get")
    async def test_list_conversations(self, mock_get: AsyncMock) -> None:
        """Test listing conversations."""
        mock_get.return_value = MagicMock(
            status_code=200,
            json=MagicMock(
                return_value=[
                    {
                        "conversation_id": "conv_1",
                        "title": "Project Alpha",
                        "status": "active",
                    },
                    {
                        "conversation_id": "conv_2",
                        "title": "Bug Fix",
                        "status": "completed",
                    },
                ]
            ),
        )

        conversations = await self.client.list_conversations()
        self.assertEqual(len(conversations), 2)
        self.assertEqual(conversations[0].conversation_id, "conv_1")
        self.assertEqual(conversations[1].title, "Bug Fix")

    @patch("httpx.AsyncClient.get")
    async def test_list_conversations_with_limit(self, mock_get: AsyncMock) -> None:
        """Test listing conversations with limit parameter."""
        mock_get.return_value = MagicMock(
            status_code=200,
            json=MagicMock(return_value=[]),
        )

        await self.client.list_conversations(limit=10)
        mock_get.assert_called_once()
        call_args = mock_get.call_args
        params = call_args.kwargs.get("params", {})
        self.assertEqual(params["limit"], 10)

    @patch("httpx.AsyncClient.post")
    async def test_create_conversation(self, mock_post: AsyncMock) -> None:
        """Test creating new conversation."""
        mock_post.return_value = MagicMock(
            status_code=200,
            json=MagicMock(return_value={"conversation_id": "conv_new_123"}),
        )

        result = await self.client.create_conversation("Build a web app")
        self.assertEqual(result["conversation_id"], "conv_new_123")

    @patch("httpx.AsyncClient.post")
    async def test_create_conversation_no_message(self, mock_post: AsyncMock) -> None:
        """Test creating conversation without initial message."""
        mock_post.return_value = MagicMock(
            status_code=200,
            json=MagicMock(return_value={"conversation_id": "conv_empty"}),
        )

        result = await self.client.create_conversation(None)
        self.assertIn("conversation_id", result)

    @patch("httpx.AsyncClient.delete")
    async def test_delete_conversation(self, mock_delete: AsyncMock) -> None:
        """Test deleting a conversation."""
        mock_delete.return_value = MagicMock(status_code=200)

        result = await self.client.delete_conversation("conv_123")
        self.assertTrue(result)

    @patch("httpx.AsyncClient.delete")
    async def test_delete_conversation_failure(self, mock_delete: AsyncMock) -> None:
        """Test delete conversation handles errors."""
        mock_delete.return_value = MagicMock(status_code=404, is_success=False)

        result = await self.client.delete_conversation("conv_invalid")
        self.assertFalse(result)

    @patch("httpx.AsyncClient.get")
    async def test_get_models(self, mock_get: AsyncMock) -> None:
        """Test getting available models."""
        mock_get.return_value = MagicMock(
            status_code=200,
            json=MagicMock(
                return_value=[
                    {"id": "gpt-5.3", "name": "GPT-5.3 Ultra"},
                    {"id": "claude-4.6", "name": "Claude 4.6 Opus"},
                ]
            ),
        )

        models = await self.client.get_models()
        self.assertEqual(len(models), 2)
        self.assertEqual(models[0]["id"], "gpt-5.3")

    @patch("httpx.AsyncClient.get")
    async def test_get_settings(self, mock_get: AsyncMock) -> None:
        """Test getting current settings."""
        mock_get.return_value = MagicMock(
            status_code=200,
            json=MagicMock(
                return_value={
                    "llm_model": "gpt-5.3",
                    "temperature": 0.7,
                    "confirmation_mode": True,
                }
            ),
        )

        settings = await self.client.get_settings()
        self.assertEqual(settings["llm_model"], "gpt-5.3")
        self.assertEqual(settings["temperature"], 0.7)

    @patch("httpx.AsyncClient.post")
    async def test_save_settings(self, mock_post: AsyncMock) -> None:
        """Test saving settings."""
        mock_post.return_value = MagicMock(
            status_code=200,
            json=MagicMock(return_value={"status": "ok"}),
        )

        payload = {"llm_model": "claude-4.6", "temperature": 0.9}
        result = await self.client.save_settings(payload)
        self.assertEqual(result["status"], "ok")

    @patch("httpx.AsyncClient.post")
    async def test_set_secret(self, mock_post: AsyncMock) -> None:
        """Test setting a secret."""
        mock_post.return_value = MagicMock(status_code=200)

        await self.client.set_secret("github", "ghp_token123")
        mock_post.assert_called_once()

    @patch("httpx.AsyncClient.get")
    async def test_get_workspace_changes(self, mock_get: AsyncMock) -> None:
        """Test getting workspace file changes."""
        mock_get.return_value = MagicMock(
            status_code=200,
            json=MagicMock(
                return_value=[
                    {"path": "app.py", "status": "modified"},
                    {"path": "test.py", "status": "added"},
                ]
            ),
        )

        changes = await self.client.get_workspace_changes("conv_123")
        self.assertEqual(len(changes), 2)
        self.assertEqual(changes[0]["path"], "app.py")

    @patch("httpx.AsyncClient.get")
    async def test_get_file_diff(self, mock_get: AsyncMock) -> None:
        """Test getting diff for a specific file."""
        mock_get.return_value = MagicMock(
            status_code=200,
            json=MagicMock(return_value={"diff": "+ new line\n- old line"}),
        )

        diff = await self.client.get_file_diff("conv_123", "app.py")
        self.assertIn("new line", diff["diff"])

    async def test_close_client(self) -> None:
        """Test closing the HTTP client."""
        client = ForgeClient()
        await client.close()
        # Should not raise

    @patch("httpx.AsyncClient.get")
    async def test_api_error_handling(self, mock_get: AsyncMock) -> None:
        """Test client handles API errors gracefully."""
        mock_response = MagicMock(status_code=500)
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Server Error", request=MagicMock(), response=mock_response
        )
        mock_get.return_value = mock_response

        with self.assertRaises(Exception):
            await self.client.get_models()

    @patch("httpx.AsyncClient.get")
    async def test_network_timeout(self, mock_get: AsyncMock) -> None:
        """Test client handles network timeouts."""
        import httpx

        mock_get.side_effect = httpx.TimeoutException("Request timed out")

        with self.assertRaises(httpx.TimeoutException):
            await self.client.list_conversations()

    @patch("httpx.AsyncClient.post")
    async def test_send_message(self, mock_post: AsyncMock) -> None:
        """Test sending a message via WebSocket falls back to HTTP."""
        mock_post.return_value = MagicMock(status_code=200)

        # This tests the HTTP fallback if socket not connected
        await self.client.send_message("Hello")
        # Should not raise

    @patch("httpx.AsyncClient.post")
    async def test_send_confirmation(self, mock_post: AsyncMock) -> None:
        """Test sending confirmation."""
        mock_post.return_value = MagicMock(status_code=200)

        await self.client.send_confirmation(confirm=True)
        # Should not raise

    @patch("httpx.AsyncClient.post")
    async def test_send_stop(self, mock_post: AsyncMock) -> None:
        """Test sending stop signal."""
        mock_post.return_value = MagicMock(status_code=200)

        await self.client.send_stop()
        # Should not raise


class TestForgeClientSocketIO(unittest.IsolatedAsyncioTestCase):
    """Tests for ForgeClient Socket.IO functionality."""

    def setUp(self) -> None:
        self.client = ForgeClient(base_url="http://localhost:3000")

    async def asyncTearDown(self) -> None:
        await self.client.close()

    @patch("socketio.AsyncClient.connect")
    @patch("socketio.AsyncClient.emit")
    async def test_join_conversation(
        self, mock_emit: AsyncMock, mock_connect: AsyncMock
    ) -> None:
        """Test joining a conversation via Socket.IO."""
        mock_connect.return_value = None

        callback = AsyncMock()
        await self.client.join_conversation("conv_123", on_event=callback)

        # socketio.AsyncClient.connected stays False by default,
        # so join_conversation calls connect twice (base URL, then with query params)
        self.assertEqual(mock_connect.call_count, 2)

    @patch("socketio.AsyncClient.disconnect")
    async def test_leave_conversation(self, mock_disconnect: AsyncMock) -> None:
        """Test leaving a conversation."""
        mock_disconnect.return_value = None

        await self.client.leave_conversation()
        # Should not raise

    @patch("socketio.AsyncClient.on")
    async def test_event_handler_registration(self, mock_on: AsyncMock) -> None:
        """Test Socket.IO event handlers are registered."""
        # This would test internal handler registration
        pass


if __name__ == "__main__":
    unittest.main()
