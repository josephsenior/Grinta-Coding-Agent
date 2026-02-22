"""Rigorous TUI Test Suite for Forge.

Tests the full push-based navigation flow:
- HomeScreen initialisation and conversation listing
- HomeScreen search and fuzzy filtering
- HomeScreen → ChatScreen transition (via open_chat)
- ChatScreen layout, model selector, and message input
- ChatScreen → back to HomeScreen (dismiss)
- Settings screen access from HomeScreen
- HelpScreen via F1 binding
- Auth bypass verification (no 401 errors)
"""

import os
import unittest
from unittest.mock import AsyncMock, MagicMock

from textual.widgets import Input, Label, ListView, Select, Static

from tui.app import ForgeApp
from tui.client import ConversationInfo, ForgeClient
from tui.screens.chat import ChatScreen
from tui.screens.home import ConversationListItem, HomeScreen
from tui.screens.settings import SettingsScreen
from tui.screens.help import HelpScreen


def _make_mock_client() -> MagicMock:
    """Create a fully-mocked ForgeClient with sensible defaults."""
    client = MagicMock(spec=ForgeClient)
    client.base_url = "http://localhost:3000"

    client.list_conversations = AsyncMock(
        return_value=[
            ConversationInfo(
                conversation_id="conv_1",
                title="Test Project Alpha",
                status="active",
            ),
            ConversationInfo(
                conversation_id="conv_2",
                title="Debug Backend Bug",
                status="completed",
            ),
            ConversationInfo(
                conversation_id="conv_3",
                title="Feature: Prompt Cache",
                status="active",
            ),
        ]
    )

    client.get_models = AsyncMock(
        return_value=[
            {"id": "gpt-5.3", "name": "GPT-5.3 (Ultra)"},
            {"id": "claude-4.6", "name": "Claude 4.6 (Opus)"},
        ]
    )

    client.get_settings = AsyncMock(
        return_value={
            "llm_model": "gpt-5.3",
            "temperature": 0.7,
        }
    )

    client.save_settings = AsyncMock(return_value={})
    client.create_conversation = AsyncMock(
        return_value={"conversation_id": "conv_new_1"}
    )
    client.join_conversation = AsyncMock(return_value=None)
    client.leave_conversation = AsyncMock(return_value=None)
    client.send_message = AsyncMock(return_value=None)
    client.send_confirmation = AsyncMock(return_value=None)
    client.send_stop = AsyncMock(return_value=None)
    client.delete_conversation = AsyncMock(return_value=True)
    client.close = AsyncMock(return_value=None)
    client.get_workspace_changes = AsyncMock(return_value=[])
    client.get_file_diff = AsyncMock(return_value={"diff": ""})
    client.set_secret = AsyncMock(return_value=None)

    return client


class TestHomeScreen(unittest.IsolatedAsyncioTestCase):
    """Tests for the HomeScreen: listing, search, and navigation triggers."""

    async def asyncSetUp(self) -> None:
        self._prev_forge_runtime = os.environ.get("FORGE_RUNTIME")
        os.environ["FORGE_RUNTIME"] = "local"
        self.client = _make_mock_client()

    async def asyncTearDown(self) -> None:
        if self._prev_forge_runtime is None:
            os.environ.pop("FORGE_RUNTIME", None)
        else:
            os.environ["FORGE_RUNTIME"] = self._prev_forge_runtime

    async def test_conversations_load(self) -> None:
        """HomeScreen should display all conversations on mount."""
        app = ForgeApp(self.client)
        async with app.run_test() as pilot:
            # Allow mount + data load
            for _ in range(5):
                await pilot.pause()

            self.assertIsInstance(app.screen, HomeScreen)

            list_view = app.screen.query_one("#conversation-list-view", ListView)
            items = list(list_view.query(ConversationListItem))
            self.assertEqual(len(items), 3)

    async def test_search_filters_conversations(self) -> None:
        """Typing in the search box should filter the conversation list."""
        app = ForgeApp(self.client)
        async with app.run_test() as pilot:
            for _ in range(5):
                await pilot.pause()

            search = app.screen.query_one("#search-input", Input)
            search.focus()
            await pilot.press(*"Bug")
            await pilot.pause()

            list_view = app.screen.query_one("#conversation-list-view", ListView)
            items = list(list_view.query(ConversationListItem))
            self.assertEqual(len(items), 1)

            title_label = items[0].query_one(
                ".conversation-title", Label
            )
            self.assertIn("Bug", str(title_label.renderable))

    async def test_search_clear_restores_list(self) -> None:
        """Clearing the search field should restore the full list."""
        app = ForgeApp(self.client)
        async with app.run_test() as pilot:
            for _ in range(5):
                await pilot.pause()

            list_view = app.screen.query_one("#conversation-list-view", ListView)
            initial_items = list(list_view.query(ConversationListItem))

            search = app.screen.query_one("#search-input", Input)
            search.focus()
            await pilot.press(*"Bug")
            await pilot.pause()

            # Clear
            search.value = ""
            # UI updates can be async; wait a few ticks for the list to settle.
            expected = len(initial_items)
            items: list[ConversationListItem] = []
            for _ in range(20):
                await pilot.pause()
                items = list(list_view.query(ConversationListItem))
                if len(items) == expected:
                    break

            self.assertEqual(len(items), expected)

    async def test_empty_state_shown_when_no_conversations(self) -> None:
        """If the backend returns no conversations, show the empty state."""
        self.client.list_conversations = AsyncMock(return_value=[])
        app = ForgeApp(self.client)
        async with app.run_test() as pilot:
            for _ in range(5):
                await pilot.pause()

            empty = app.screen.query_one("#empty-state", Static)
            self.assertTrue(empty.display)

            list_view = app.screen.query_one("#conversation-list-view", ListView)
            self.assertFalse(list_view.display)


class TestNavigation(unittest.IsolatedAsyncioTestCase):
    """Tests for screen transitions: Home→Chat, Home→Settings, F1→Help."""

    async def asyncSetUp(self) -> None:
        self._prev_forge_runtime = os.environ.get("FORGE_RUNTIME")
        os.environ["FORGE_RUNTIME"] = "local"
        self.client = _make_mock_client()

    async def asyncTearDown(self) -> None:
        if self._prev_forge_runtime is None:
            os.environ.pop("FORGE_RUNTIME", None)
        else:
            os.environ["FORGE_RUNTIME"] = self._prev_forge_runtime

    async def test_select_conversation_pushes_chat(self) -> None:
        """Selecting a conversation in the list should push ChatScreen."""
        app = ForgeApp(self.client)
        async with app.run_test() as pilot:
            for _ in range(5):
                await pilot.pause()

            # Use open_chat directly (tests the navigation helper)
            app.open_chat("conv_1")
            for _ in range(8):
                await pilot.pause()

            self.assertIsInstance(app.screen, ChatScreen)
            self.assertEqual(app.screen.conversation_id, "conv_1")

    async def test_dismiss_returns_to_home(self) -> None:
        """Dismissing ChatScreen should pop back to HomeScreen."""
        app = ForgeApp(self.client)
        async with app.run_test() as pilot:
            for _ in range(5):
                await pilot.pause()

            # Push chat
            app.open_chat("conv_1")
            for _ in range(8):
                await pilot.pause()
            self.assertIsInstance(app.screen, ChatScreen)

            # Pop back via the action method (same as ctrl+q binding)
            app.screen.action_go_home()
            for _ in range(8):
                await pilot.pause()
            self.assertIsInstance(app.screen, HomeScreen)

    async def test_settings_screen_opens(self) -> None:
        """Ctrl+S from HomeScreen should push SettingsScreen."""
        app = ForgeApp(self.client)
        async with app.run_test() as pilot:
            for _ in range(5):
                await pilot.pause()

            await pilot.press("ctrl+s")
            for _ in range(5):
                await pilot.pause()

            self.assertIsInstance(app.screen, SettingsScreen)

    async def test_help_screen_opens(self) -> None:
        """F1 from any screen should push HelpScreen."""
        app = ForgeApp(self.client)
        async with app.run_test() as pilot:
            for _ in range(5):
                await pilot.pause()

            await pilot.press("f1")
            for _ in range(5):
                await pilot.pause()

            self.assertIsInstance(app.screen, HelpScreen)

    async def test_escape_dismisses_help(self) -> None:
        """Pressing Escape from HelpScreen should pop back."""
        app = ForgeApp(self.client)
        async with app.run_test() as pilot:
            for _ in range(5):
                await pilot.pause()

            await pilot.press("f1")
            for _ in range(3):
                await pilot.pause()
            self.assertIsInstance(app.screen, HelpScreen)

            await pilot.press("escape")
            for _ in range(3):
                await pilot.pause()
            self.assertIsInstance(app.screen, HomeScreen)


class TestChatScreen(unittest.IsolatedAsyncioTestCase):
    """Tests for the ChatScreen: model selector, input, messages."""

    async def asyncSetUp(self) -> None:
        self._prev_forge_runtime = os.environ.get("FORGE_RUNTIME")
        os.environ["FORGE_RUNTIME"] = "local"
        self.client = _make_mock_client()

    async def asyncTearDown(self) -> None:
        if self._prev_forge_runtime is None:
            os.environ.pop("FORGE_RUNTIME", None)
        else:
            os.environ["FORGE_RUNTIME"] = self._prev_forge_runtime

    async def test_model_selector_loads(self) -> None:
        """Model selector should populate from the API."""
        app = ForgeApp(self.client)
        async with app.run_test() as pilot:
            for _ in range(5):
                await pilot.pause()

            app.open_chat("conv_1")
            for _ in range(8):
                await pilot.pause()

            select = app.screen.query_one("#model-selector", Select)
            # _options is a list of (prompt, value) tuples
            option_values = [opt[1] for opt in select._options]
            self.assertIn("gpt-5.3", option_values)
            self.assertIn("claude-4.6", option_values)

    async def test_message_input_sends(self) -> None:
        """Typing a message and pressing Enter should call send_message."""
        app = ForgeApp(self.client)
        async with app.run_test() as pilot:
            for _ in range(5):
                await pilot.pause()

            app.open_chat("conv_1")
            for _ in range(8):
                await pilot.pause()

            chat_input = app.screen.query_one("#chat-input", Input)
            chat_input.focus()
            await pilot.press(*"Hello Forge")
            await pilot.press("enter")
            for _ in range(3):
                await pilot.pause()

            self.client.send_message.assert_awaited_once_with("Hello Forge")


class TestSettingsScreen(unittest.IsolatedAsyncioTestCase):
    """Tests for the SettingsScreen: model dropdown, save."""

    async def asyncSetUp(self) -> None:
        self._prev_forge_runtime = os.environ.get("FORGE_RUNTIME")
        os.environ["FORGE_RUNTIME"] = "local"
        self.client = _make_mock_client()

    async def asyncTearDown(self) -> None:
        if self._prev_forge_runtime is None:
            os.environ.pop("FORGE_RUNTIME", None)
        else:
            os.environ["FORGE_RUNTIME"] = self._prev_forge_runtime

    async def test_models_load_in_settings(self) -> None:
        """Settings model dropdown should populate from the API."""
        app = ForgeApp(self.client)
        async with app.run_test() as pilot:
            for _ in range(5):
                await pilot.pause()

            app.open_settings()
            for _ in range(8):
                await pilot.pause()

            self.assertIsInstance(app.screen, SettingsScreen)
            select = app.screen.query_one("#model-select", Select)
            option_values = [opt[1] for opt in select._options]
            self.assertIn("gpt-5.3", option_values)

    async def test_escape_closes_settings(self) -> None:
        """Pressing Escape should dismiss settings and return to Home."""
        app = ForgeApp(self.client)
        async with app.run_test() as pilot:
            for _ in range(5):
                await pilot.pause()

            app.open_settings()
            for _ in range(5):
                await pilot.pause()

            await pilot.press("escape")
            for _ in range(3):
                await pilot.pause()
            self.assertIsInstance(app.screen, HomeScreen)


class TestAuthBypass(unittest.IsolatedAsyncioTestCase):
    """Verify that local runtime mode produces no 401 errors."""

    async def test_no_unauthorized_errors(self) -> None:
        prev = os.environ.get("FORGE_RUNTIME")
        os.environ["FORGE_RUNTIME"] = "local"
        client = _make_mock_client()
        try:
            app = ForgeApp(client)
            async with app.run_test() as pilot:
                for _ in range(5):
                    await pilot.pause()

                all_statics = app.screen.query(Static)
                for s in all_statics:
                    rendered = str(s.renderable)
                    self.assertNotIn("401", rendered)
                    self.assertNotIn("Unauthorized", rendered)
        finally:
            if prev is None:
                os.environ.pop("FORGE_RUNTIME", None)
            else:
                os.environ["FORGE_RUNTIME"] = prev


if __name__ == "__main__":
    unittest.main()
