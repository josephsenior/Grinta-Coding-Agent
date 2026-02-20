"""End-of-day summary screen — shows what Forge did today.

Reads from ``.forge/changelog.jsonl`` and aggregates:
- Sessions started
- Tasks completed / errored
- Total cost
- Files touched
- Commands run
- Web pages visited

Views:
  [t] today   [w] this week   [m] this month   [a] all time
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, UTC, timedelta
from typing import Any

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.screen import Screen
from textual.widgets import Footer, Header, Static

from backend.core.workspace_context import (
    detect_project_type,
    read_today_changelog,
    read_week_changelog,
    read_month_changelog,
    read_all_changelog,
)

_VIEW_LABELS = {
    "today": "TODAY",
    "week": "THIS WEEK",
    "month": "THIS MONTH",
    "all": "ALL TIME",
}


def _div() -> Static:
    return Static("─" * 42, classes="sum-divider")


def _bar_chart(daily_costs: dict[str, float], width: int = 30) -> str:
    """Render a compact ASCII bar chart of daily costs.

    Args:
        daily_costs: Mapping of date string (YYYY-MM-DD) to cost (USD).
        width: Width of the bar in characters.

    Returns:
        Multiline string suitable for a Static widget.
    """
    if not daily_costs:
        return ""
    max_cost = max(daily_costs.values()) if daily_costs else 0.0
    if max_cost == 0:
        return ""
    lines = []
    for date, cost in sorted(daily_costs.items()):
        bar_len = int((cost / max_cost) * width)
        bar = "█" * bar_len
        day_label = date[5:]  # MM-DD
        lines.append(f"  {day_label}  {bar}  ${cost:.4f}")
    return "\n".join(lines)


class SummaryScreen(Screen[None]):
    """Multi-view summary: today / week / month / all-time cost and activity."""

    BINDINGS = [
        Binding("escape", "go_back", "Back", show=True),
        Binding("t", "view_today", "Today", show=True),
        Binding("w", "view_week", "Week", show=True),
        Binding("m", "view_month", "Month", show=True),
        Binding("a", "view_all", "All time", show=True),
    ]

    CSS = """
    SummaryScreen {
        background: black;
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
    .sum-chart {
        color: $primary;
        margin: 0 0 0 2;
    }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._view: str = "today"   # "today" | "week" | "month" | "all"

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield VerticalScroll(id="sum-scroll")
        yield Footer()

    async def on_mount(self) -> None:
        await self._render()

    async def _render(self) -> None:
        scroll = self.query_one("#sum-scroll", VerticalScroll)
        await scroll.remove_children()

        now = datetime.now(UTC)

        if self._view == "today":
            entries = read_today_changelog()
            period = f"TODAY  ({now.strftime('%Y-%m-%d')})"
        elif self._view == "week":
            entries = read_week_changelog()
            week_start = (now - timedelta(days=6)).strftime("%Y-%m-%d")
            period = f"THIS WEEK  ({week_start} → {now.strftime('%Y-%m-%d')})"
        elif self._view == "month":
            entries = read_month_changelog()
            period = f"THIS MONTH  ({now.strftime('%Y-%m')})"
        else:
            entries = read_all_changelog()
            period = "ALL TIME"

        await scroll.mount(Static(f"📊  FORGE SUMMARY — {period}", classes="sum-title"))
        await scroll.mount(
            Static(
                f"Project: {detect_project_type()}",
                classes="sum-row-dim",
            )
        )

        # ── View toggle hint ───────────────────────────────────────
        await scroll.mount(
            Static(
                "[t] today  [w] week  [m] month  [a] all time",
                classes="sum-row-dim",
            )
        )
        await scroll.mount(_div())

        if not entries:
            await scroll.mount(
                Static(
                    "No activity recorded yet.\nStart a session and come back!",
                    classes="sum-row",
                )
            )
            return

        stats = _aggregate(entries)

        # ── Activity ──────────────────────────────────────────────
        await scroll.mount(Static("ACTIVITY", classes="sum-heading"))
        await scroll.mount(
            Static(f"  🗨  Conversations:    {stats['sessions']}", classes="sum-row")
        )
        await scroll.mount(
            Static(
                f"  ✅ Tasks completed:  {stats['tasks_done']}",
                classes="sum-row sum-ok",
            )
        )
        if stats["tasks_error"]:
            await scroll.mount(
                Static(
                    f"  ⚠️  Tasks errored:    {stats['tasks_error']}",
                    classes="sum-row sum-warn",
                )
            )
        if stats["commands_run"]:
            await scroll.mount(
                Static(f"  🖥️  Commands run:     {stats['commands_run']}", classes="sum-row")
            )
        if stats["browses"]:
            await scroll.mount(
                Static(f"  🌐 Pages visited:    {stats['browses']}", classes="sum-row")
            )
        await scroll.mount(_div())

        # ── Cost ──────────────────────────────────────────────────
        await scroll.mount(Static("COST", classes="sum-heading"))
        await scroll.mount(
            Static(f"  💰 Total:  ${stats['total_cost']:.4f}", classes="sum-row")
        )
        # Per-session breakdown (top 5)
        for cid, cost in sorted(
            stats["session_costs"].items(), key=lambda x: x[1], reverse=True
        )[:5]:
            await scroll.mount(
                Static(f"     {cid[:8]}…  ${cost:.4f}", classes="sum-row-dim")
            )

        # ── Daily bar chart (week / month / all) ──────────────────
        if self._view != "today" and stats["daily_costs"]:
            await scroll.mount(_div())
            await scroll.mount(Static("DAILY SPEND", classes="sum-heading"))
            chart = _bar_chart(stats["daily_costs"])
            if chart:
                await scroll.mount(Static(chart, classes="sum-chart"))

            # Average daily cost
            if stats["daily_costs"]:
                avg = sum(stats["daily_costs"].values()) / len(stats["daily_costs"])
                peak_date, peak_cost = max(stats["daily_costs"].items(), key=lambda x: x[1])
                await scroll.mount(
                    Static(f"  Avg/day: ${avg:.4f}   Peak: {peak_date[5:]} ${peak_cost:.4f}",
                           classes="sum-row-dim")
                )

        await scroll.mount(_div())

        # ── Files ─────────────────────────────────────────────────
        await scroll.mount(Static("FILES", classes="sum-heading"))
        await scroll.mount(
            Static(f"  📁 Unique files touched:  {len(stats['files'])}", classes="sum-row")
        )
        await scroll.mount(
            Static(f"  ✏️  Edits:                 {stats['edits']}", classes="sum-row")
        )
        await scroll.mount(
            Static(f"  🆕 New files created:     {stats['new_files']}", classes="sum-row")
        )
        if stats["files"]:
            await scroll.mount(_div())
            await scroll.mount(Static("CHANGED FILES", classes="sum-heading"))
            for f in sorted(stats["files"])[:25]:
                name = f.replace("\\", "/").split("/")[-1]
                await scroll.mount(Static(f"  • {name}", classes="sum-row-dim"))
            if len(stats["files"]) > 25:
                await scroll.mount(
                    Static(
                        f"  … and {len(stats['files']) - 25} more",
                        classes="sum-row-dim",
                    )
                )

        await scroll.mount(_div())

    # ── view toggle actions ───────────────────────────────────────

    async def action_view_today(self) -> None:
        self._view = "today"
        await self._render()

    async def action_view_week(self) -> None:
        self._view = "week"
        await self._render()

    async def action_view_month(self) -> None:
        self._view = "month"
        await self._render()

    async def action_view_all(self) -> None:
        self._view = "all"
        await self._render()

    def action_go_back(self) -> None:
        self.dismiss()


def _aggregate(entries: list[dict[str, Any]]) -> dict[str, Any]:
    sessions: set[str] = set()
    files: set[str] = set()
    edits = 0
    new_files = 0
    total_cost: float = 0.0
    session_costs: dict[str, float] = defaultdict(float)
    daily_costs: dict[str, float] = defaultdict(float)
    tasks_done = 0
    tasks_error = 0
    commands_run = 0
    browses = 0

    # Track latest cost per session per day
    session_day_cost: dict[str, float] = defaultdict(float)

    for e in entries:
        cid = e.get("conversation_id", "")
        date = e.get("date", "")
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
            session_key = f"{cid}:{date}"
            if cost > session_day_cost[session_key]:
                # Adjust the daily total and session total by the delta
                delta = cost - session_day_cost[session_key]
                session_day_cost[session_key] = cost
                if date:
                    daily_costs[date] = daily_costs.get(date, 0.0) + delta
            if cost > session_costs[cid]:
                session_costs[cid] = cost
        elif ev == "task_finished":
            tasks_done += 1
        elif ev == "task_error":
            tasks_error += 1
        elif ev == "command_run":
            commands_run += 1
        elif ev == "browse":
            browses += 1

    total_cost = sum(session_costs.values())

    return {
        "sessions": len(sessions),
        "files": files,
        "edits": edits,
        "new_files": new_files,
        "total_cost": total_cost,
        "session_costs": dict(session_costs),
        "daily_costs": dict(daily_costs),
        "tasks_done": tasks_done,
        "tasks_error": tasks_error,
        "commands_run": commands_run,
        "browses": browses,
    }

