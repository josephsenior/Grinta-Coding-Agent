"""Diff rendering for file edit observations in the CLI."""

from __future__ import annotations

from typing import Any

from rich.console import Console, ConsoleOptions, RenderResult
from rich.panel import Panel
from rich.text import Text


class DiffPanel:
    """Rich renderable that shows a unified diff for a file edit."""

    def __init__(self, obs: Any) -> None:
        self._obs = obs

    def __rich_console__(
        self, console: Console, options: ConsoleOptions
    ) -> RenderResult:
        obs = self._obs
        path = getattr(obs, "path", "?")
        prev_exist = getattr(obs, "prev_exist", True)

        # New file creation — no diff, just show creation note
        if not prev_exist:
            new_content = getattr(obs, "new_content", None) or getattr(obs, "content", "")
            line_count = new_content.count("\n") + 1 if new_content else 0
            yield Panel(
                Text(f"+ new file ({line_count} lines)", style="green"),
                title=f"[bold green]created[/bold green] {path}",
                border_style="green",
                padding=(0, 1),
            )
            return

        # Try get_edit_groups for structured diff
        groups = None
        if hasattr(obs, "get_edit_groups"):
            try:
                groups = obs.get_edit_groups(n_context_lines=3)
            except Exception:
                pass

        if groups:
            diff_text = self._render_groups(groups)
            yield Panel(
                diff_text,
                title=f"[bold yellow]edited[/bold yellow] {path}",
                border_style="yellow",
                padding=(0, 1),
            )
            return

        # Fallback: visualize_diff or plain content
        diff_str = None
        if hasattr(obs, "visualize_diff"):
            try:
                diff_str = obs.visualize_diff(n_context_lines=3)
            except Exception:
                pass

        if diff_str:
            yield Panel(
                Text(diff_str[:3000]),
                title=f"[bold yellow]edited[/bold yellow] {path}",
                border_style="yellow",
                padding=(0, 1),
            )
        else:
            yield Panel(
                Text(f"✓ written", style="green"),
                title=f"[bold green]wrote[/bold green] {path}",
                border_style="green",
                padding=(0, 1),
            )

    @staticmethod
    def _render_groups(groups: list[dict[str, list[str]]]) -> Text:
        """Build a Rich Text from edit groups with colored +/- lines."""
        result = Text()
        for i, group in enumerate(groups):
            if i > 0:
                result.append("  ···\n", style="dim")
            for line in group.get("before_edits", []):
                result.append(line + "\n", style="red")
            for line in group.get("after_edits", []):
                result.append(line + "\n", style="green")
        # Truncate if too long
        if len(result.plain) > 3000:
            result.truncate(3000)
            result.append("\n… (truncated)", style="dim")
        return result
