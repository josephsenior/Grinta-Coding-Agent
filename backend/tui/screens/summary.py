"""End-of-day summary screen — shows what Forge did today.

Reads from ``.forge/changelog.jsonl`` and aggregates:
- Sessions started
- Tasks completed / errored
- Total cost
- Files touched
- Commands run
- Web pages visited
"""

from __future__ import annotations

from datetime import datetime, UTC
from typing import Any

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.screen import Screen
from textual.widgets import Footer, Header, Static

from backend.core.workspace_context import (
    detect_project_type,
    read_today_changelog,
    read_all_changelog,
)


def _div() -> Static:
    return Static("─" * 42, classes="sum-divider")


class SummaryScreen(Screen[None]):
    """End-of-day summary: aggregates the agent changelog for today."""

    BINDINGS = [
        Binding("escape", "go_back", "Back", show=True),
        Binding("a", "toggle_all", "All time", show=True),
    ]

    CSS = """
    SummaryScreen {
        background: $surface;
    }
    #sum-scroll {
        height: 100%;
        padding: 1 3;
    }
    .sum-title {
        text-style: bold;
        color: $accent;
        text-align: center;
        margin-bottom: 1;
    }
    .sum-heading {
        text-style: bold;
        color: $primary;
        margin: 1 0 0 0;
    }
    .sum-row {
        color: $text;
        margin: 0 0 0 2;
    }
    .sum-row-dim {
        color: $text-muted;
        margin: 0 0 0 4;
    }
    .sum-divider {
        color: $primary-darken-2;
        margin: 1 0;
    }
    .sum-ok {
        color: $success;
    }
    .sum-warn {
        color: $warning;
    }
    .sum-err {
        color: $error;
    }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._show_all = False

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield VerticalScroll(id="sum-scroll")
        yield Footer()

    async def on_mount(self) -> None:
        await self._render()

    async def _render(self) -> None:
        scroll = self.query_one("#sum-scroll", VerticalScroll)
        await scroll.remove_children()

        if self._show_all:
            entries = read_all_changelog()
            period = "ALL TIME"
        else:
            entries = read_today_changelog()
            now = datetime.now(UTC)
            period = f"TODAY  ({now.strftime('%Y-%m-%d')})"

        await scroll.mount(Static(f"📊  FORGE SUMMARY — {period}", classes="sum-title"))
        await scroll.mount(Static(
            f"Project: {detect_project_type()}",
            classes="sum-row-dim",
        ))
        await scroll.mount(_div())

        if not entries:
            await scroll.mount(Static(
                "No activity recorded yet.\nStart a session and come back!",
                classes="sum-row",
            ))
            return

        stats = _aggregate(entries)

        # ── Activity ──────────────────────────────────────────────
        await scroll.mount(Static("ACTIVITY", classes="sum-heading"))
        await scroll.mount(Static(
            f"  🗨  Conversations:    {stats['sessions']}",
            classes="sum-row",
        ))
        await scroll.mount(Static(
            f"  ✅ Tasks completed:  {stats['tasks_done']}",
            classes="sum-row sum-ok",
        ))
        if stats["tasks_error"]:
            await scroll.mount(Static(
                f"  ⚠️  Tasks errored:    {stats['tasks_error']}",
                classes="sum-row sum-warn",
            ))
        if stats["commands_run"]:
            await scroll.mount(Static(
                f"  🖥️  Commands run:     {stats['commands_run']}",
                classes="sum-row",
            ))
        if stats["browses"]:
            await scroll.mount(Static(
                f"  🌐 Pages visited:    {stats['browses']}",
                classes="sum-row",
            ))
        await scroll.mount(_div())

        # ── Cost ──────────────────────────────────────────────────
        await scroll.mount(Static("COST", classes="sum-heading"))
        await scroll.mount(Static(
            f"  💰 Total:  ${stats['total_cost']:.4f}",
            classes="sum-row",
        ))
        # Per-session breakdown (top 5)
        for cid, cost in sorted(
            stats["session_costs"].items(), key=lambda x: x[1], reverse=True
        )[:5]:
            await scroll.mount(Static(
                f"     {cid[:8]}…  ${cost:.4f}",
                classes="sum-row-dim",
            ))
        await scroll.mount(_div())

        # ── Files ─────────────────────────────────────────────────
        await scroll.mount(Static("FILES", classes="sum-heading"))
        await scroll.mount(Static(
            f"  📁 Unique files touched:  {len(stats['files'])}",
            classes="sum-row",
        ))
        await scroll.mount(Static(
            f"  ✏️  Edits:                 {stats['edits']}",
            classes="sum-row",
        ))
        await scroll.mount(Static(
            f"  🆕 New files created:     {stats['new_files']}",
            classes="sum-row",
        ))
        if stats["files"]:
            await scroll.mount(_div())
            await scroll.mount(Static("CHANGED FILES", classes="sum-heading"))
            for f in sorted(stats["files"])[:25]:
                name = f.replace("\\", "/").split("/")[-1]
                await scroll.mount(Static(f"  • {name}", classes="sum-row-dim"))
            if len(stats["files"]) > 25:
                await scroll.mount(Static(
                    f"  … and {len(stats['files']) - 25} more",
                    classes="sum-row-dim",
                ))

        hint = "(press [a] to toggle all-time view)" if not self._show_all else "(press [a] for today only)"
        await scroll.mount(_div())
        await scroll.mount(Static(hint, classes="sum-row-dim"))

    async def action_toggle_all(self) -> None:
        self._show_all = not self._show_all
        await self._render()

    def action_go_back(self) -> None:
        self.dismiss()


def _aggregate(entries: list[dict[str, Any]]) -> dict[str, Any]:
    from collections import defaultdict

    sessions: set[str] = set()
    files: set[str] = set()
    edits = 0
    new_files = 0
    total_cost: float = 0.0
    session_costs: dict[str, float] = defaultdict(float)
    tasks_done = 0
    tasks_error = 0
    commands_run = 0
    browses = 0

    for e in entries:
        cid = e.get("conversation_id", "")
        if cid:
            sessions.add(cid)
        ev = e.get("event", "")
        path = e.get("path", "")

        if ev == "file_edit":
            if path:
                files.add(path)
            edits += 1
        elif ev == "file_write":
            if path:
                files.add(path)
            new_files += 1
        elif ev == "cost_update":
            cost = float(e.get("cost", 0.0))
            if cost > total_cost:
                total_cost = cost
            if cid:
                session_costs[cid] = max(session_costs[cid], cost)
        elif ev == "task_finished":
            tasks_done += 1
        elif ev == "task_error":
            tasks_error += 1
        elif ev == "command_run":
            commands_run += 1
        elif ev == "browse":
            browses += 1

    return {
        "sessions": len(sessions),
        "files": files,
        "edits": edits,
        "new_files": new_files,
        "total_cost": total_cost,
        "session_costs": dict(session_costs),
        "tasks_done": tasks_done,
        "tasks_error": tasks_error,
        "commands_run": commands_run,
        "browses": browses,
    }
