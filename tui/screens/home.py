"""Home screen — conversation list and new-conversation input."""

from __future__ import annotations

from datetime import datetime, timezone

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
    Select,
    Static,
)

from tui.client import ConversationInfo, ForgeClient
from backend.core.workspace_context import (
    detect_project_type,
    get_conversation_meta,
    list_projects,
    list_all_tags,
    set_conversation_tags,
    today_stats,
)


def _relative_time(iso_str: str) -> str:
    """Turn an ISO-8601 timestamp into a human-friendly relative label."""
    if not iso_str:
        return ""
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        now = datetime.now(tz=timezone.utc)
        delta = now - dt
        seconds = int(delta.total_seconds())
        if seconds < 60:
            return "just now"
        if seconds < 3600:
            return f"{seconds // 60}m ago"
        if seconds < 86400:
            return f"{seconds // 3600}h ago"
        if seconds < 172800:
            return "yesterday"
        if seconds < 604800:
            return f"{seconds // 86400}d ago"
        return dt.strftime("%b %d")
    except Exception:
        return ""


_STATUS_ICON = {
    "running": "● ",
    "loading": "◌ ",
    "finished": "✓ ",
    "stopped": "■ ",
    "error": "✗ ",
    "rejected": "✗ ",
    "paused": "⏸ ",
    "awaiting_user_input": "? ",
    "awaiting_user_confirmation": "? ",
}

_STATUS_CSS = {
    "running": "status-running",
    "loading": "status-running",
    "finished": "status-finished",
    "stopped": "status-stopped",
    "error": "status-error",
    "rejected": "status-error",
    "paused": "status-paused",
    "awaiting_user_input": "status-paused",
    "awaiting_user_confirmation": "status-paused",
}


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
        status = (self.info.status or "unknown").lower()
        icon = _STATUS_ICON.get(status, "· ")
        css = _STATUS_CSS.get(status, "status-unknown")
        time_label = _relative_time(self.info.last_updated_at or self.info.created_at)
        with Horizontal(classes="conversation-item"):
            yield Label(self.info.title or "Untitled", classes="conversation-title")
            if self.info.project:
                yield Label(f"[{self.info.project}]", classes="conversation-project")
            if self.info.tags:
                tags_str = " ".join(f"#{t}" for t in self.info.tags[:3])
                yield Label(tags_str, classes="conversation-tags")
            yield Label(f"{icon}{status}", classes=f"status-pill {css}")
            yield Label(time_label, classes="conversation-meta")


class HomeScreen(Screen[None]):
    """Landing screen — lists conversations and lets the user create new ones.

    Navigation:
    - Selecting a conversation pushes ChatScreen via ``app.open_chat()``.
    - Creating a new conversation does the same.
    - This screen stays on the stack so returning from ChatScreen is instant.

    Tagging:
    - Prefix your new task with ``[project] #tag1 #tag2`` to set project/tags.
      Example: ``[myapp] #bug fix the login crash``
    - Press ``t`` on a highlighted conversation to edit its tags inline.
    - The project selector at the top filters conversations by project.
    """

    BINDINGS = [
        Binding("ctrl+n", "focus_new", "New", show=True),
        Binding("ctrl+s", "open_settings", "Settings", show=True),
        Binding("ctrl+y", "open_summary", "Summary", show=True),
        Binding("ctrl+q", "quit_app", "Quit", show=True),
        Binding("ctrl+f", "focus_search", "Search", show=True),
        # Single-char bindings only fire when a non-Input widget has focus
        Binding("r", "refresh_list", "Refresh", show=False),
        Binding("d", "delete_selected", "Delete", show=False),
        Binding("/", "focus_search", "Search", show=False),
        Binding("t", "tag_selected", "Tag", show=False),
    ]

    def __init__(self, client: ForgeClient) -> None:
        super().__init__()
        self.client = client
        self._conversations: list[ConversationInfo] = []
        self._search_query = ""
        self._active_project: str = ""   # "" means "all projects"

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Vertical(id="home-outer"):
            with Vertical(id="home-header"):
                yield Static(
                    # Dot-matrix logo — each letter is 5 rows × 4 cols of ● / space
                    # F        O        R        G        E
                    "● ● ●   ● ● ●   ● ● ●   ● ● ●   ● ● ●\n"
                    "●       ●   ●   ●   ●   ●         ●    \n"
                    "● ● ●   ●   ●   ● ● ●   ●  ● ●   ● ● ●\n"
                    "●       ●   ●   ● ●     ●   ●     ●    \n"
                    "●       ● ● ●   ●  ●    ● ● ●   ● ● ●  ",
                    id="home-logo",
                )
                yield Static("", id="home-title")
                yield Static(
                    "local-first AI coding agent",
                    id="home-subtitle",
                )
                yield Static("", id="home-fingerprint")
                yield Static("", id="home-stats")
            with Horizontal(id="filter-bar"):
                yield Select[str](
                    [("All projects", "")],
                    id="project-select",
                    prompt="Project",
                    allow_blank=False,
                    value="",
                )
                yield Input(
                    placeholder="🔍  Search conversations…",
                    id="search-input",
                )
            with Vertical(id="list-area"):
                yield ListView(id="conversation-list-view")
                yield Static(
                    "No conversations yet.\nType a task below and press Enter to begin.",
                    id="empty-state",
                )
            with Horizontal(id="new-bar"):
                yield Input(
                    placeholder="✦  Task… prefix with [project] and #tags  e.g. [myapp] #bug fix login",
                    id="new-input",
                )
        yield Footer()

    async def on_mount(self) -> None:
        """Load conversations when the screen mounts."""
        self._refresh_workspace_info()
        await self._load_conversations()
        self._refresh_project_selector()

    async def on_screen_resume(self) -> None:
        """Refresh the list when returning from ChatScreen."""
        self._refresh_workspace_info()
        await self._load_conversations()
        self._refresh_project_selector()

    def _refresh_workspace_info(self) -> None:
        """Update the fingerprint and today's stats labels."""
        try:
            fingerprint = detect_project_type()
            fp_widget = self.query_one("#home-fingerprint", Static)
            fp_widget.update(fingerprint)
        except Exception:
            pass
        try:
            stats = today_stats()
            sessions = stats.get("sessions", 0)
            cost = stats.get("total_cost", 0.0)
            tasks = stats.get("tasks_done", 0)
            stats_widget = self.query_one("#home-stats", Static)
            stats_widget.update(
                f"Today: {sessions} session{'s' if sessions != 1 else ''}"
                f" · ${cost:.4f} · {tasks} task{'s' if tasks != 1 else ''} done"
            )
        except Exception:
            pass

    def _refresh_project_selector(self) -> None:
        """Rebuild the project dropdown from the local tags store."""
        try:
            projects = list_projects()
            options: list[tuple[str, str]] = [("All projects", "")]
            for p in projects:
                options.append((p, p))
            sel = self.query_one("#project-select", Select)
            sel.set_options(options)
            # Preserve selection if the project still exists
            if self._active_project and self._active_project not in projects:
                self._active_project = ""
            sel.value = self._active_project
        except Exception:
            pass

    # ── data loading ──────────────────────────────────────────────

    async def _load_conversations(self) -> None:
        try:
            raw = await self.client.list_conversations(limit=50)
        except Exception as e:
            self._show_empty(f"Error loading conversations: {e}")
            return

        # Merge in local tag metadata
        enriched: list[ConversationInfo] = []
        for info in raw:
            meta = get_conversation_meta(info.conversation_id)
            from dataclasses import replace as dc_replace

            enriched.append(
                dc_replace(
                    info,
                    tags=tuple(meta.get("tags", [])),
                    project=meta.get("project", ""),
                )
            )
        self._conversations = enriched
        self._apply_filter()

    def _apply_filter(self) -> None:
        """Filter and display conversations based on current search query and project."""
        list_view = self.query_one("#conversation-list-view", ListView)
        list_view.clear()

        # Project filter
        filtered = self._conversations
        if self._active_project:
            filtered = [c for c in filtered if c.project == self._active_project]

        # Search filter
        if self._search_query:
            scored = []
            for conv in filtered:
                score = self._fuzzy_match_score(self._search_query, conv)
                if score > 0:
                    scored.append((score, conv))
            scored.sort(key=lambda x: x[0], reverse=True)
            filtered = [conv for _, conv in scored]

        if not filtered and self._conversations:
            label = f'No conversations match "{self._search_query}"'
            if self._active_project:
                label = f"No conversations in project [{self._active_project}]"
                if self._search_query:
                    label += f' matching "{self._search_query}"'
            self._show_empty(label)
            return

        if not filtered:
            self._show_empty("No conversations yet — type below to start one.")
            return

        # Hide empty state, show list
        self.query_one("#empty-state", Static).display = False
        list_view.display = True
        for info in filtered:
            list_view.append(ConversationListItem(info))

    def _show_empty(self, message: str) -> None:
        """Show the empty-state label and hide the list."""
        self.query_one("#conversation-list-view", ListView).display = False
        empty = self.query_one("#empty-state", Static)
        empty.update(message)
        empty.display = True

    @staticmethod
    def _fuzzy_match_score(query: str, conv: ConversationInfo) -> float:
        """Score a conversation against a search query using fuzzy matching."""
        query_lower = query.lower()
        title = (conv.title or "").lower()
        status = conv.status.lower()
        cid = conv.conversation_id.lower()
        project = conv.project.lower()
        tags = " ".join(conv.tags)

        if query_lower in title:
            return 100.0
        if query_lower in project:
            return 90.0
        if query_lower.lstrip("#") in tags:
            return 85.0
        if query_lower in status:
            return 80.0
        if query_lower in cid:
            return 70.0

        score = _fuzzy_subsequence_score(query_lower, title)
        if score > 0:
            return score

        words = query_lower.split()
        if words:
            matched = sum(
                1
                for w in words
                if w in title or w in status or w in cid or w.lstrip("#") in tags or w in project
            )
            if matched == len(words):
                return 60.0
            if matched > 0:
                return 30.0 * (matched / len(words))

        return 0.0

    # ── input handling ────────────────────────────────────────────

    @on(Select.Changed, "#project-select")
    def _on_project_changed(self, event: Select.Changed) -> None:
        value = event.value
        self._active_project = "" if (value is Select.BLANK or value is None) else str(value)
        self._apply_filter()

    @on(Input.Changed, "#search-input")
    def _on_search_changed(self, event: Input.Changed) -> None:
        """Filter conversations as user types in search box."""
        self._search_query = event.value.strip()
        self._apply_filter()

    @on(ListView.Selected, "#conversation-list-view")
    def _on_conversation_selected(self, event: ListView.Selected) -> None:
        item = event.item
        if isinstance(item, ConversationListItem):
            self.app.open_chat(item.info.conversation_id)  # type: ignore[attr-defined]

    # ── actions ───────────────────────────────────────────────────

    @staticmethod
    def _parse_task_input(raw: str) -> tuple[str, str, list[str]]:
        """Parse ``[project] #tag1 #tag2 task description`` from free-form input.

        Returns ``(task, project, tags)``.
        """
        import re

        task = raw
        project = ""
        tags: list[str] = []

        # Extract [project] prefix
        m = re.match(r"^\[([^\]]+)\]\s*", task)
        if m:
            project = m.group(1).strip()
            task = task[m.end():]

        # Extract #tags
        def _extract_tags(text: str) -> tuple[str, list[str]]:
            found = re.findall(r"#(\w+)", text)
            cleaned = re.sub(r"#\w+\s*", "", text).strip()
            return cleaned, found

        task, tags = _extract_tags(task)
        return task, project, tags

    async def _create_and_open(self, initial_message: str | None) -> None:
        """Parse tags/project from input, create a conversation, then push the chat screen."""
        self.notify("Creating conversation…", severity="information")
        task = initial_message or ""
        project = ""
        tags: list[str] = []

        if task:
            task, project, tags = self._parse_task_input(task)

        try:
            result = await self.client.create_conversation(task or None)
            cid = result.get("conversation_id", "")
            if cid:
                # Persist project/tags locally
                if project or tags:
                    set_conversation_tags(cid, tags, project=project)
                    self._refresh_project_selector()
                self.query_one("#new-input", Input).value = ""
                self.app.open_chat(cid)  # type: ignore[attr-defined]
            else:
                self.notify("Failed to get conversation_id", severity="error")
        except Exception as e:
            msg = str(e)
            if (
                "SETTINGS_NOT_FOUND" in msg
                or "LLM settings" in msg
                or "Settings not found" in msg
            ):
                self.notify(
                    "LLM not configured. Press Ctrl+S to open Settings and add your API key.",
                    severity="error",
                    timeout=8,
                )
            else:
                self.notify(f"Error: {msg}", severity="error", timeout=6)

    def action_focus_new(self) -> None:
        self.query_one("#new-input", Input).focus()

    def action_focus_search(self) -> None:
        self.query_one("#search-input", Input).focus()

    def action_open_settings(self) -> None:
        self.app.open_settings()  # type: ignore[attr-defined]

    def action_open_summary(self) -> None:
        self.app.open_summary()  # type: ignore[attr-defined]

    def action_quit_app(self) -> None:
        self.app.exit()

    async def action_refresh_list(self) -> None:
        await self._load_conversations()
        self._refresh_project_selector()
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

    def action_tag_selected(self) -> None:
        """Open a tag-edit input for the highlighted conversation."""
        list_view = self.query_one("#conversation-list-view", ListView)
        item = list_view.highlighted_child
        if not isinstance(item, ConversationListItem):
            self.notify("Select a conversation first", severity="warning")
            return
        cid = item.info.conversation_id
        current_tags = " ".join(f"#{t}" for t in item.info.tags)
        project = item.info.project

        # Populate new-input with existing metadata for easy editing
        new_input = self.query_one("#new-input", Input)
        prefix = f"[{project}] " if project else ""
        new_input.value = f"{prefix}{current_tags}"
        new_input.focus()
        self.notify(
            f"Edit tags for {cid[:8]}… then press Enter to save  (empty = clear)",
            severity="information",
            timeout=8,
        )
        # Override next submit to update tags rather than create a new conversation
        self._pending_tag_cid = cid

    # Override submit handler to intercept tag-edit mode
    _pending_tag_cid: str | None = None

    @on(Input.Submitted, "#new-input")  # type: ignore[override]
    async def _on_new_or_tag_input(self, event: Input.Submitted) -> None:
        if self._pending_tag_cid:
            cid = self._pending_tag_cid
            self._pending_tag_cid = None
            raw = event.value.strip()
            task, project, tags = self._parse_task_input(raw)
            set_conversation_tags(cid, tags, project=project or None)
            self.query_one("#new-input", Input).value = ""
            self._refresh_project_selector()
            await self._load_conversations()
            self.notify(
                f"Updated tags for {cid[:8]}…: project=[{project}] tags={tags}",
                severity="information",
            )
        else:
            msg = event.value.strip()
            await self._create_and_open(msg or None)
