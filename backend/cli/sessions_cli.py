"""Session retention CLI — list / show / export / delete past sessions.

Backs the ``grinta sessions ...`` subcommand. Reuses ``cli.session_manager``
helpers so the slash-command UI and the CLI subcommand share one source of
truth for what counts as "a session".
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.table import Table


@dataclass(frozen=True)
class _SessionResolveFailure:
    message: str


def _root() -> Path | None:
    from backend.cli.session_manager import _find_sessions_root

    return _find_sessions_root(None)


def _entries() -> list[tuple[str, dict[str, Any], int, Path]]:
    """[(session_id, metadata, event_count, path), ...] sorted newest first."""
    root = _root()
    if root is None:
        return []
    from backend.cli.session_manager import _list_session_entries

    base = _list_session_entries(root)
    out: list[tuple[str, dict[str, Any], int, Path]] = []
    for sid, meta, count in base:
        out.append((sid, meta, count, root / sid))
    return out


def cmd_list(console: Console, limit: int = 50) -> int:
    if limit < 1:
        console.print("[red]--limit must be 1 or greater.[/red]")
        return 2
    rows = _entries()[:limit]
    if not rows:
        console.print("[dim]No sessions found.[/dim]")
        return 0
    table = Table(title="Sessions", border_style="dim")
    table.add_column("#", style="dim")
    table.add_column("ID")
    table.add_column("Title")
    table.add_column("Model", style="dim")
    table.add_column("Events", justify="right")
    table.add_column("Cost", justify="right")
    table.add_column("Updated", style="dim")
    for i, (sid, meta, count, _path) in enumerate(rows, 1):
        title = str(meta.get("title") or meta.get("name") or "—")
        model = str(meta.get("llm_model") or "—")[:24]
        cost = meta.get("accumulated_cost") or 0
        cost_str = f"${cost:.4f}" if cost else "—"
        updated = str(meta.get("last_updated_at") or meta.get("created_at") or "—")[:19]
        table.add_row(str(i), sid[:12], title, model, str(count), cost_str, updated)
    console.print(table)
    return 0


def _resolve(
    target: str,
) -> tuple[str, dict[str, Any], int, Path] | _SessionResolveFailure | None:
    rows = _entries()
    if not rows:
        return None
    cleaned = (target or "").strip()
    if cleaned.isdigit():
        index = int(cleaned)
        if 1 <= index <= len(rows):
            return rows[index - 1]
        return None

    exact = [row for row in rows if row[0] == cleaned]
    if exact:
        return exact[0]

    matches = [row for row in rows if row[0].startswith(cleaned)]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        preview = ", ".join(row[0][:12] for row in matches[:4])
        if len(matches) > 4:
            preview += ", ..."
        return _SessionResolveFailure(
            f"Session prefix '{cleaned}' is ambiguous ({len(matches)} matches: {preview}). Use a longer id."
        )
    return None


def _report_resolve_failure(console: Console, target: str) -> int:
    console.print(f"[red]No session matches:[/red] {target}")
    return 2


def cmd_show(console: Console, target: str) -> int:
    row = _resolve(target)
    if isinstance(row, _SessionResolveFailure):
        console.print(f"[red]{row.message}[/red]")
        return 2
    if row is None:
        return _report_resolve_failure(console, target)
    sid, meta, count, path = row
    console.print(f"[bold]Session[/bold] {sid}")
    console.print(f"  path:   {path}")
    console.print(f"  events: {count}")
    if meta:
        console.print("  metadata:")
        for k, v in meta.items():
            console.print(f"    {k}: {v}")
    return 0


def cmd_export(console: Console, target: str, out_path: str) -> int:
    row = _resolve(target)
    if isinstance(row, _SessionResolveFailure):
        console.print(f"[red]{row.message}[/red]")
        return 2
    if row is None:
        return _report_resolve_failure(console, target)
    sid, _meta, _count, path = row
    out = Path(out_path).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.suffix.lower() == ".zip":
        archive = shutil.make_archive(str(out.with_suffix("")), "zip", root_dir=path)
        console.print(f"Wrote [bold]{archive}[/bold]")
    else:
        # Tree copy.
        shutil.copytree(path, out, dirs_exist_ok=True)
        console.print(f"Copied to [bold]{out}[/bold]")
    return 0


def cmd_delete(console: Console, target: str, *, yes: bool = False) -> int:
    row = _resolve(target)
    if isinstance(row, _SessionResolveFailure):
        console.print(f"[red]{row.message}[/red]")
        return 2
    if row is None:
        return _report_resolve_failure(console, target)
    sid, _meta, _count, path = row
    if not yes:
        from rich.prompt import Confirm

        if not Confirm.ask(
            f"Delete session {sid}? This cannot be undone.", default=False
        ):
            console.print("[dim]Aborted.[/dim]")
            return 0
    shutil.rmtree(path, ignore_errors=True)
    console.print(f"Deleted [bold]{sid}[/bold]")
    return 0


def cmd_prune(console: Console, *, days: int = 30, yes: bool = False) -> int:
    """Delete sessions older than ``days``."""
    if days < 0:
        console.print("[red]--days must be 0 or greater.[/red]")
        return 2
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    rows = _entries()
    to_delete: list[tuple[str, Path]] = []
    for sid, meta, _count, path in rows:
        ts = meta.get("last_updated_at") or meta.get("created_at")
        if not ts:
            # No timestamp → fall back to mtime.
            mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
            if mtime < cutoff:
                to_delete.append((sid, path))
            continue
        try:
            parsed = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            if parsed < cutoff:
                to_delete.append((sid, path))
        except Exception:
            continue

    if not to_delete:
        console.print(f"[dim]No sessions older than {days} days.[/dim]")
        return 0

    console.print(
        f"Will delete [bold]{len(to_delete)}[/bold] sessions older than {days} days."
    )
    if not yes:
        from rich.prompt import Confirm

        if not Confirm.ask("Proceed?", default=False):
            console.print("[dim]Aborted.[/dim]")
            return 0
    for sid, path in to_delete:
        shutil.rmtree(path, ignore_errors=True)
        console.print(f"  deleted {sid}")
    return 0


__all__ = ["cmd_list", "cmd_show", "cmd_export", "cmd_delete", "cmd_prune"]
