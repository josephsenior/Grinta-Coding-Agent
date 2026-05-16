"""Diff rendering for file edit observations in the CLI."""

from __future__ import annotations

import os
from typing import Any

from rich import box
from rich.console import Console, ConsoleOptions, Group, RenderResult
from rich.panel import Panel
from rich.text import Text

from backend.cli.theme import (
    CLR_CARD_BORDER,
    CLR_CARD_TITLE,
    CLR_STATUS_WARN,
    CLR_WARN_BODY,
)
from backend.cli.transcript import (
    format_activity_delta_secondary,
    format_activity_primary,
    format_activity_result_secondary,
    format_activity_secondary,
    format_activity_validation_callout,
)


def _is_validation_secondary(text: str) -> bool:
    """True for syntax / lint / type feedback bundled with file edits."""
    low = (text or '').lower()
    return any(
        frag in low
        for frag in (
            'syntax error',
            'syntax check',
            'lint error',
            'linter',
            'eslint',
            'ruff:',
            'ruff ',
            'flake8',
            'pylint',
            'mypy',
            'pyright',
            'type error',
            'typecheck',
        )
    )


def _extract_indentation_warnings(content: str) -> tuple[str, list[str] | None]:
    """Extract indentation warnings from content string.

    Returns (content_without_warnings, warnings_list) where warnings_list
    is None if no warnings found.
    """
    marker = '[INDENTATION WARNINGS]'
    idx = content.find(marker)
    if idx == -1:
        return content, None

    # Split content into main part and warnings
    main_content = content[:idx].rstrip()
    warnings_str = content[idx + len(marker):].strip()

    # Parse warnings into structured list
    warnings: list[str] = []
    current_warning: list[str] = []
    for line in warnings_str.split('\n'):
        line = line.strip()
        if line.startswith('[INDENTATION MISMATCH]') or line.startswith('[INDENTATION ERROR]'):
            if current_warning:
                warnings.append('\n'.join(current_warning))
                current_warning = []
        if line:
            current_warning.append(line)
    if current_warning:
        warnings.append('\n'.join(current_warning))

    return main_content, warnings if warnings else None


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
            # Check for indentation warnings in content
            self._append_indentation_warnings(parts, obs)
            yield self._build_panel(parts)
            return

        # GRINTA_SHOW_DIFF=0: hide full diff output
        if os.environ.get('GRINTA_SHOW_DIFF', '1') == '0':
            parts.append(format_activity_result_secondary('updated', kind='ok'))
            # Check for indentation warnings in content
            self._append_indentation_warnings(parts, obs)
            yield self._build_panel(parts)
            return

        # Try get_edit_groups for structured diff
        groups = self._extract_edit_groups()
        if groups:
            self._append_groups_diff(parts, groups)
            # Check for indentation warnings in content
            self._append_indentation_warnings(parts, obs)
            yield self._build_panel(parts)
            return

        # Fallback: visualize_diff or embedded diff
        diff_str = self._extract_visualize_diff()
        if diff_str:
            parts.append(Text(diff_str[:3000]))
            # Check for indentation warnings in content
            self._append_indentation_warnings(parts, obs)
            yield self._build_panel(parts)
            return

        embedded = self._extract_embedded_diff()
        if embedded:
            parts.append(Text(embedded[:3000]))
            # Check for indentation warnings in content
            self._append_indentation_warnings(parts, obs)
            yield self._build_panel(parts)
            return

        parts.append(format_activity_result_secondary('updated', kind='ok'))
        # Check for indentation warnings in content
        self._append_indentation_warnings(parts, obs)
        yield self._build_panel(parts)

    def _append_indentation_warnings(self, parts: list[Any], obs: Any) -> None:
        """Append styled indentation warnings if present in observation content."""
        content = getattr(obs, 'content', None) or getattr(obs, 'output', '')
        if not content:
            return

        main_content, warnings = _extract_indentation_warnings(content)
        if not warnings:
            return

        # Add a separator
        parts.append(Text(''))

        # Add warning header
        parts.append(Text('⚠ Indentation Warnings', style=f'bold {CLR_STATUS_WARN}'))
        parts.append(Text(''))

        # Add each warning with styling
        for warning in warnings:
            # Parse warning components
            lines = warning.split('\n')
            for line in lines:
                if line.startswith('[INDENTATION MISMATCH]'):
                    # Style mismatch warnings
                    text = line.replace('[INDENTATION MISMATCH] ', '')
                    parts.append(Text(f'  ⚠ {text}', style=CLR_STATUS_WARN))
                elif line.startswith('[INDENTATION ERROR]'):
                    # Style error warnings
                    text = line.replace('[INDENTATION ERROR] ', '')
                    parts.append(Text(f'  ✗ {text}', style=CLR_STATUS_WARN))
                elif line.startswith('[BROKEN LINE]'):
                    # Style broken line
                    text = line.replace('[BROKEN LINE] ', '')
                    parts.append(Text(f'    → {text}', style=CLR_WARN_BODY))
                elif line.startswith('[SUGGESTED FIX]'):
                    # Style suggested fix
                    text = line.replace('[SUGGESTED FIX] ', '')
                    parts.append(Text(f'    💡 {text}', style=CLR_WARN_BODY))

        # Add a separator
        parts.append(Text(''))

    def _append_secondary(self, parts: list[Any]) -> None:
        if not self._secondary:
            return
        if _is_validation_secondary(self._secondary):
            parts.append(format_activity_validation_callout(self._secondary))
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

    def _extract_embedded_diff(self) -> str | None:
        """Extract diff embedded in content string (via [EDIT_DIFF] marker)."""
        obs = self._obs
        content = getattr(obs, 'content', None)
        if not content:
            return None
        marker = '[EDIT_DIFF]'
        idx = content.find(marker)
        if idx == -1:
            return None
        return content[idx + len(marker) :].lstrip('\n')

    def _append_groups_diff(
        self,
        parts: list[Any],
        groups: list[dict[str, list[str]]],
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
            title=Text('', style=CLR_CARD_TITLE),
            title_align='left',
            border_style=CLR_CARD_BORDER,
            box=box.SQUARE,
            padding=(0, 0),
        )

    @staticmethod
    def _render_groups(groups: list[dict[str, list[str]]]) -> Any:
        """Build a Rich Syntax from edit groups with colored +/- lines."""
        from rich.syntax import Syntax

        lines = []
        for i, group in enumerate(groups):
            if i > 0:
                lines.append('···\n')
            for line in group.get('before_edits', []):
                lines.append(line + '\n')
            for line in group.get('after_edits', []):
                lines.append(line + '\n')

        diff_str = ''.join(lines)
        if len(diff_str) > 3000:
            diff_str = diff_str[:3000] + '\n… (truncated)'

        return Syntax(
            diff_str,
            lexer='diff',
            theme='material',
            word_wrap=True,
            padding=(0, 1),
            background_color='#060a14',
            line_numbers=True,
        )
