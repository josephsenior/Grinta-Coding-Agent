"""Diff rendering for file edit observations in the CLI."""

from __future__ import annotations

from typing import Any

from rich import box
from rich.console import Console, ConsoleOptions, Group, RenderResult
from rich.panel import Panel
from rich.text import Text

from backend.cli.theme import (
    CLR_CARD_BORDER,
    CLR_CARD_TITLE,
    CLR_DIFF_ADD,
    CLR_DIFF_REM,
)
from backend.cli.transcript import (
    format_activity_delta_secondary,
    format_activity_primary,
    format_activity_result_secondary,
    format_activity_secondary,
)


class DiffPanel:
    """Rich renderable that shows a unified diff for a file edit."""

    def __init__(
        self,
        obs: Any,
        *,
        verb: str | None = None,
        detail: str | None = None,
        secondary: str | None = None,
    ) -> None:
        self._obs = obs
        self._verb = verb
        self._detail = detail
        self._secondary = secondary

    def __rich_console__(
        self, console: Console, options: ConsoleOptions
    ) -> RenderResult:
        obs = self._obs
        path = getattr(obs, 'path', '?')
        prev_exist = getattr(obs, 'prev_exist', True)
        verb = self._verb or ('Created' if not prev_exist else 'Edited')
        parts: list[Any] = [format_activity_primary(verb, self._detail or path)]
        self._append_secondary(parts)

        # New file creation — no diff, just show creation note
        if not prev_exist:
            self._append_new_file_delta(parts)
            yield self._build_panel(parts)
            return

        # Try get_edit_groups for structured diff
        groups = self._extract_edit_groups()
        if groups:
            self._append_groups_diff(parts, groups)
            yield self._build_panel(parts)
            return

        # Fallback: visualize_diff or plain content
        diff_str = self._extract_visualize_diff()
        if diff_str:
            parts.append(Text(diff_str[:3000]))
            yield self._build_panel(parts)
            return

        parts.append(format_activity_result_secondary('updated', kind='ok'))
        # Filter out syntax check messages if they exist to reduce visual clutter
        filtered_parts = [
            p
            for p in parts
            if not (isinstance(p, Text) and 'CRITICAL: Syntax Error' in p.plain)
        ]
        yield self._build_panel(filtered_parts)

    def _append_secondary(self, parts: list[Any]) -> None:
        # Hide syntax error messages from UI to reduce clutter
        if not self._secondary:
            return
        if 'Syntax Error' in self._secondary or 'Syntax Check' in self._secondary:
            return
        parts.append(format_activity_secondary(self._secondary, kind='neutral'))

    def _append_new_file_delta(self, parts: list[Any]) -> None:
        obs = self._obs
        new_content = getattr(obs, 'new_content', None) or getattr(obs, 'content', '')
        line_count = len(new_content.splitlines()) if new_content else 0
        delta = format_activity_delta_secondary(added=line_count)
        if delta is not None:
            parts.append(delta)

    def _extract_edit_groups(self) -> list[dict[str, list[str]]] | None:
        obs = self._obs
        if not hasattr(obs, 'get_edit_groups'):
            return None
        try:
            return obs.get_edit_groups(n_context_lines=3)
        except Exception:
            return None

    def _extract_visualize_diff(self) -> str | None:
        obs = self._obs
        if not hasattr(obs, 'visualize_diff'):
            return None
        try:
            return obs.visualize_diff(n_context_lines=3)
        except Exception:
            return None

    def _append_groups_diff(
        self, parts: list[Any], groups: list[dict[str, list[str]]],
    ) -> None:
        diff_text = self._render_groups(groups)
        added = sum(
            1
            for g in groups
            for line in g.get('after_edits', [])
            if line.startswith('+')
        )
        removed = sum(
            1
            for g in groups
            for line in g.get('before_edits', [])
            if line.startswith('-')
        )
        delta = format_activity_delta_secondary(added=added, removed=removed)
        if delta is not None:
            parts.append(delta)
        parts.append(diff_text)

    @staticmethod
    def _build_panel(parts: list[Any]) -> Panel:
        return Panel(
            Group(*parts),
            title=Text('File', style=CLR_CARD_TITLE),
            title_align='left',
            border_style=CLR_CARD_BORDER,
            box=box.ROUNDED,
            padding=(0, 1),
        )

    @staticmethod
    def _render_groups(groups: list[dict[str, list[str]]]) -> Text:
        """Build a Rich Text from edit groups with colored +/- lines."""
        result = Text()
        for i, group in enumerate(groups):
            if i > 0:
                result.append('  ···\n', style='dim')
            for line in group.get('before_edits', []):
                result.append(line + '\n', style=CLR_DIFF_REM)
            for line in group.get('after_edits', []):
                result.append(line + '\n', style=CLR_DIFF_ADD)
        # Truncate if too long
        if len(result.plain) > 3000:
            result.truncate(3000)
            result.append('\n… (truncated)', style='dim')
        return result
