"""Diff viewer screen — shows workspace file changes for the current conversation."""

from __future__ import annotations

from typing import Any

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, VerticalScroll
from textual.screen import Screen
from textual.widgets import (
    Footer,
    Header,
    Label,
    ListItem,
    ListView,
    Static,
)

from backend.tui.client import ForgeClient


class DiffFileItem(ListItem):
    """A single changed file in the diff list."""

    def __init__(self, filepath: str, status: str) -> None:
        super().__init__()
        self.filepath = filepath
        self.file_status = status

    def compose(self) -> ComposeResult:
        icon = {"added": "+", "modified": "~", "deleted": "-"}.get(
            self.file_status, "?"
        )
        colour = {"added": "green", "modified": "yellow", "deleted": "red"}.get(
            self.file_status, "white"
        )
        yield Label(f"[{colour}]{icon}[/] {self.filepath}")


class DiffScreen(Screen[None]):
    """Two-panel diff viewer: file list on left, diff content on right.

    Fetches workspace changes from ``GET /api/git/changes`` and individual
    diffs from ``GET /api/git/diff``.
    """

    BINDINGS = [
        Binding("escape", "go_back", "Back", show=True),
        Binding("r", "refresh", "Refresh", show=True),
    ]

    CSS = """
    #diff-outer {
        height: 100%;
    }
    #file-list {
        width: 30;
        border-right: vkey $primary;
    }
    #diff-content {
        width: 1fr;
        padding: 0 1;
    }
    .diff-line-add {
        color: $success;
    }
    .diff-line-del {
        color: $error;
    }
    .diff-line-hdr {
        color: $accent;
        text-style: bold;
    }
    .diff-line-ctx {
        color: $text-muted;
    }
    .empty-diff {
        height: 100%;
        content-align: center middle;
        color: $text-muted;
        text-style: italic;
    }
    """

    def __init__(self, client: ForgeClient, conversation_id: str) -> None:
        super().__init__()
        self.client = client
        self.conversation_id = conversation_id
        self._changes: list[dict[str, Any]] = []

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id="diff-outer"):
            yield ListView(id="file-list")
            yield VerticalScroll(
                Static("Select a file to view its diff", classes="empty-diff"),
                id="diff-content",
            )
        yield Footer()

    async def on_mount(self) -> None:
        await self._load_changes()

    async def _load_changes(self) -> None:
        file_list = self.query_one("#file-list", ListView)
        file_list.clear()
        try:
            self._changes = await self.client.get_workspace_changes(
                self.conversation_id
            )
        except Exception as e:
            self.notify(f"Error loading changes: {e}", severity="error")
            return

        if not self._changes:
            await file_list.mount(Static("No workspace changes", classes="empty-diff"))
            return

        for change in self._changes:
            filepath = change.get("path", change.get("filename", "unknown"))
            status = change.get("status", "modified")
            file_list.append(DiffFileItem(filepath, status))

    @on(ListView.Selected, "#file-list")
    async def _on_file_selected(self, event: ListView.Selected) -> None:
        item = event.item
        if not isinstance(item, DiffFileItem):
            return
        await self._show_diff(item.filepath)

    async def _show_diff(self, filepath: str) -> None:
        container = self.query_one("#diff-content", VerticalScroll)
        await container.remove_children()

        try:
            diff_data = await self.client.get_file_diff(self.conversation_id, filepath)
        except Exception as e:
            await container.mount(Static(f"Error: {e}", classes="empty-diff"))
            return

        diff_text: str = str(diff_data.get("diff", diff_data.get("content", "")))
        if not diff_text:
            await container.mount(
                Static("No diff content available", classes="empty-diff")
            )
            return

        # Render as coloured diff lines
        lines = diff_text.splitlines()
        await container.mount(Static(f"── {filepath} ──", classes="diff-line-hdr"))
        for line in lines:
            if line.startswith(("+++", "---", "@@")):
                await container.mount(Static(line, classes="diff-line-hdr"))
            elif line.startswith("+"):
                await container.mount(Static(line, classes="diff-line-add"))
            elif line.startswith("-"):
                await container.mount(Static(line, classes="diff-line-del"))
            else:
                await container.mount(Static(line, classes="diff-line-ctx"))

    # ── actions ───────────────────────────────────────────────────

    def action_go_back(self) -> None:
        self.dismiss()

    async def action_refresh(self) -> None:
        await self._load_changes()
        self.notify("Refreshed")
