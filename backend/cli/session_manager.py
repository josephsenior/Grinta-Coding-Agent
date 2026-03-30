"""Session management — list, inspect, and resume past sessions."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.table import Table
logger = logging.getLogger(__name__)


def _find_sessions_root() -> Path | None:
    """Locate the conversation storage directory."""
    import os

    app_root = os.environ.get("APP_ROOT", os.getcwd())
    candidates = [
        Path(app_root) / "storage" / ".app" / "conversations",
        Path(app_root) / "storage" / "sessions",
        Path.home() / ".grinta" / "sessions",
    ]
    for path in candidates:
        if path.is_dir():
            return path
    return None


def _load_metadata(session_dir: Path) -> dict[str, Any] | None:
    """Load metadata.json from a session directory."""
    import json

    meta_path = session_dir / "metadata.json"
    if not meta_path.exists():
        return None
    try:
        with meta_path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        logger.debug("Could not load metadata from %s", meta_path, exc_info=True)
        return None


def _count_events(session_dir: Path) -> int:
    """Count persisted events in a session directory."""
    events_dir = session_dir / "events"
    if events_dir.is_dir():
        return sum(1 for f in events_dir.iterdir() if f.suffix == ".json")
    return 0


def list_sessions(console: Console, *, limit: int = 20) -> None:
    """Display a table of past sessions."""
    root = _find_sessions_root()
    if root is None:
        console.print("[dim]No session storage found.[/dim]")
        return

    sessions: list[tuple[str, dict[str, Any], int]] = []
    for entry in root.iterdir():
        if not entry.is_dir():
            continue
        meta = _load_metadata(entry)
        event_count = _count_events(entry)
        sessions.append((entry.name, meta or {}, event_count))

    if not sessions:
        console.print("[dim]No past sessions found.[/dim]")
        return

    # Sort by last_updated_at or created_at descending
    def _sort_key(item: tuple[str, dict[str, Any], int]) -> str:
        m = item[1]
        return m.get("last_updated_at", m.get("created_at", "0"))

    sessions.sort(key=_sort_key, reverse=True)
    sessions = sessions[:limit]

    table = Table(title="Past Sessions", border_style="bright_black", show_lines=False)
    table.add_column("#", style="dim", width=3)
    table.add_column("Session ID", style="cyan", max_width=32)
    table.add_column("Title", max_width=40)
    table.add_column("Model", style="blue", max_width=20)
    table.add_column("Events", justify="right", style="yellow")
    table.add_column("Cost", justify="right", style="green")
    table.add_column("Updated", style="dim", max_width=19)

    for i, (sid, meta, event_count) in enumerate(sessions, 1):
        title = meta.get("title", meta.get("name", "—"))
        model = meta.get("llm_model", "—")
        cost = meta.get("accumulated_cost", 0)
        cost_str = f"${cost:.4f}" if cost else "—"
        updated = meta.get("last_updated_at", meta.get("created_at", "—"))
        if isinstance(updated, str) and len(updated) > 19:
            updated = updated[:19]

        table.add_row(
            str(i),
            sid[:32],
            str(title)[:40] if title else "—",
            str(model)[:20] if model else "—",
            str(event_count),
            cost_str,
            str(updated),
        )

    console.print(table)
    console.print(
        "[dim]Use /resume <N> or /resume <session_id> to resume a session.[/dim]"
    )


def get_session_id_by_index(index: int) -> str | None:
    """Get a session ID by its index from the list (1-based)."""
    root = _find_sessions_root()
    if root is None:
        return None

    sessions: list[tuple[str, dict[str, Any]]] = []
    for entry in root.iterdir():
        if not entry.is_dir():
            continue
        meta = _load_metadata(entry)
        sessions.append((entry.name, meta or {}))

    def _sort_key(item: tuple[str, dict[str, Any]]) -> str:
        m = item[1]
        return m.get("last_updated_at", m.get("created_at", "0"))

    sessions.sort(key=_sort_key, reverse=True)

    if 1 <= index <= len(sessions):
        return sessions[index - 1][0]
    return None
