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


def _fuzzy_subsequence_score(query: str, target: str) -> float:
    """Score how well query characters appear in order within target.

    Returns a score 0-50 based on character matching and gap penalties.
    Returns 0 if not all characters are found in sequence.
    """
    if not query or not target:
        return 0.0

    qi = 0
    total_gap = 0
    last_match = -1

    for ti, char in enumerate(target):
        if qi < len(query) and char == query[qi]:
            if last_match >= 0:
                total_gap += ti - last_match - 1
            last_match = ti
            qi += 1

    if qi < len(query):
        return 0.0  # Not all chars matched

    # Score: penalize large gaps between matched characters
    base_score = 50.0
    gap_penalty = min(total_gap * 2.0, 40.0)
    return max(base_score - gap_penalty, 5.0)


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
        Binding("ctrl+f", "focus_search", "Search", show=True),
        Binding("/", "focus_search", "Search", show=False),
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
    #search-bar {
        height: 3;
        padding: 0 2;
    }
    #search-input {
        width: 1fr;
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
        self._search_query = ""

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Vertical(id="home-container"):
            with Vertical(id="home-header"):
                yield Static("⚒  FORGE", id="home-header-text")
                yield Static(
                    "AI-Powered Development — Terminal Edition", id="home-hint"
                )
            with Horizontal(id="search-bar"):
                yield Input(
                    placeholder="Search conversations (Ctrl+F or /)...",
                    id="search-input",
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

        self._apply_filter()

    def _apply_filter(self) -> None:
        """Filter and display conversations based on current search query."""
        list_view = self.query_one("#conversation-list-view", ListView)
        list_view.clear()

        # Filter conversations by search query (fuzzy matching)
        filtered = self._conversations
        if self._search_query:
            scored = []
            for conv in self._conversations:
                score = self._fuzzy_match_score(self._search_query, conv)
                if score > 0:
                    scored.append((score, conv))
            scored.sort(key=lambda x: x[0], reverse=True)
            filtered = [conv for _, conv in scored]

        if not filtered and self._conversations:
            list_view.mount(
                Static(
                    f'No conversations match "{self._search_query}"',
                    classes="empty-hint",
                )
            )
            return

        if not filtered:
            list_view.mount(
                Static(
                    "No conversations yet — type below to start one.",
                    classes="empty-hint",
                )
            )
            return

        for info in filtered:
            list_view.append(ConversationListItem(info))

    @staticmethod
    def _fuzzy_match_score(query: str, conv: ConversationInfo) -> float:
        """Score a conversation against a search query using fuzzy matching.

        Returns a score > 0 if the conversation matches, 0 otherwise.
        Higher scores indicate better matches.
        """
        query_lower = query.lower()
        title = (conv.title or "").lower()
        status = conv.status.lower()
        cid = conv.conversation_id.lower()

        # Exact substring match (highest priority)
        if query_lower in title:
            return 100.0
        if query_lower in status:
            return 80.0
        if query_lower in cid:
            return 70.0

        # Fuzzy: all query characters appear in order in the target
        score = _fuzzy_subsequence_score(query_lower, title)
        if score > 0:
            return score

        # Word-level matching: each query word found somewhere
        words = query_lower.split()
        if words:
            matched = sum(
                1 for w in words if w in title or w in status or w in cid
            )
            if matched == len(words):
                return 60.0
            if matched > 0:
                return 30.0 * (matched / len(words))

        return 0.0

    # ── input handling ────────────────────────────────────────────

    @on(Input.Changed, "#search-input")
    def _on_search_changed(self, event: Input.Changed) -> None:
        """Filter conversations as user types in search box."""
        self._search_query = event.value.strip()
        self._apply_filter()

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

    def action_focus_search(self) -> None:
        self.query_one("#search-input", Input).focus()

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
