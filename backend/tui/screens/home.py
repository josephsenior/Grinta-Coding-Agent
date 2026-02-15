"""Home screen — conversation list and new-conversation input."""

from __future__ import annotations


from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import (
    Footer,
    Header,
    Input,
    Label,
    ListItem,
    ListView,
    Static,
)

from backend.tui.client import ConversationInfo, ForgeClient


class ConversationListItem(ListItem):
    """Single row in the conversation list."""

    def __init__(self, info: ConversationInfo) -> None:
        super().__init__()
        self.info = info

    def compose(self) -> ComposeResult:
        with Horizontal():
            yield Label(self.info.title or "Untitled", classes="conversation-title")
            yield Label(
                self.info.status,
                classes="conversation-meta",
            )


class HomeScreen(Screen[str]):
    """Landing screen — lists conversations and lets the user create new ones.

    Returns the chosen ``conversation_id`` when the user selects or creates one.
    """

    BINDINGS = [
        Binding("ctrl+n", "focus_input", "New conversation", show=True),
        Binding("ctrl+s", "open_settings", "Settings", show=True),
        Binding("ctrl+q", "quit_app", "Quit", show=True),
        Binding("r", "refresh_list", "Refresh", show=True),
        Binding("d", "delete_selected", "Delete", show=True),
    ]

    CSS = """
    #home-header {
        height: 5;
        content-align: center middle;
        padding: 1;
    }
    #home-header-text {
        text-align: center;
        text-style: bold;
        color: $accent;
    }
    #home-hint {
        text-align: center;
        color: $text-muted;
    }
    #conversation-list-view {
        height: 1fr;
        border: round $primary;
        margin: 0 2;
    }
    #new-bar {
        height: 3;
        dock: bottom;
        padding: 0 2;
    }
    #new-input {
        width: 1fr;
    }
    .empty-hint {
        height: 100%;
        content-align: center middle;
        color: $text-muted;
        text-style: italic;
    }
    """

    def __init__(self, client: ForgeClient) -> None:
        super().__init__()
        self.client = client
        self._conversations: list[ConversationInfo] = []

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Vertical(id="home-container"):
            with Vertical(id="home-header"):
                yield Static("⚒  FORGE", id="home-header-text")
                yield Static(
                    "AI-Powered Development — Terminal Edition", id="home-hint"
                )
            yield ListView(id="conversation-list-view")
            with Horizontal(id="new-bar"):
                yield Input(
                    placeholder="Describe a task to start a new conversation…",
                    id="new-input",
                )
        yield Footer()

    async def on_mount(self) -> None:
        """Load conversations when the screen mounts."""
        await self._load_conversations()

    # ── data loading ──────────────────────────────────────────────

    async def _load_conversations(self) -> None:
        list_view = self.query_one("#conversation-list-view", ListView)
        list_view.clear()
        try:
            self._conversations = await self.client.list_conversations(limit=50)
        except Exception as e:
            list_view.mount(
                Static(f"Error loading conversations: {e}", classes="empty-hint")
            )
            return

        if not self._conversations:
            list_view.mount(
                Static(
                    "No conversations yet — type below to start one.",
                    classes="empty-hint",
                )
            )
            return

        for info in self._conversations:
            list_view.append(ConversationListItem(info))

    # ── input handling ────────────────────────────────────────────

    @on(Input.Submitted, "#new-input")
    async def _on_new_conversation(self, event: Input.Submitted) -> None:
        msg = event.value.strip()
        if not msg:
            # Create a blank conversation
            pass
        await self._create_and_open(msg or None)

    @on(ListView.Selected, "#conversation-list-view")
    def _on_conversation_selected(self, event: ListView.Selected) -> None:
        item = event.item
        if isinstance(item, ConversationListItem):
            self.dismiss(item.info.conversation_id)

    # ── actions ───────────────────────────────────────────────────

    async def _create_and_open(self, initial_message: str | None) -> None:
        """Create a conversation then switch to the chat screen."""
        self.notify("Creating conversation…", severity="information")
        try:
            result = await self.client.create_conversation(initial_message)
            cid = result.get("conversation_id", "")
            if cid:
                self.dismiss(cid)
            else:
                self.notify(
                    "Failed to get conversation_id from server", severity="error"
                )
        except Exception as e:
            self.notify(f"Error: {e}", severity="error")

    def action_focus_input(self) -> None:
        self.query_one("#new-input", Input).focus()

    def action_open_settings(self) -> None:
        from backend.tui.screens.settings import SettingsScreen

        self.app.push_screen(SettingsScreen(self.client))

    def action_quit_app(self) -> None:
        self.app.exit()

    async def action_refresh_list(self) -> None:
        await self._load_conversations()
        self.notify("Refreshed", severity="information")

    async def action_delete_selected(self) -> None:
        list_view = self.query_one("#conversation-list-view", ListView)
        item = list_view.highlighted_child
        if isinstance(item, ConversationListItem):
            cid = item.info.conversation_id
            ok = await self.client.delete_conversation(cid)
            if ok:
                self.notify(f"Deleted {cid[:8]}…")
                await self._load_conversations()
            else:
                self.notify("Delete failed", severity="error")
