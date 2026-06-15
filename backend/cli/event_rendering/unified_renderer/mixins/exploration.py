"""Activity card builders — exploration domain."""

from __future__ import annotations

from backend.cli.event_rendering.unified_renderer.types import (
    ActivityCard,
    ActivityLine,
)
from backend.cli.event_rendering.unified_renderer.utils import _SEARCH_CARD_PRESETS
from backend.cli.theme import NAVY_TEXT_DIM, NAVY_TEXT_MUTED


class _ExplorationMixin:
    @staticmethod
    def _build_search_results_secondary(
        match_count: int,
        file_count: int,
        *,
        source_tool: str = 'search',
        output_mode: str | None = None,
    ) -> str:
        if source_tool == 'glob':
            if file_count == 1:
                return '1 file'
            if file_count:
                return f'{file_count} files'
            return 'no files'
        if source_tool == 'find_symbols':
            if match_count == 1:
                suffix = f' · {file_count} files' if file_count else ''
                return f'1 symbol{suffix}'
            if match_count:
                suffix = f' · {file_count} files' if file_count else ''
                return f'{match_count} symbols{suffix}'
            return 'no symbols'
        if source_tool == 'grep' and output_mode == 'files_with_matches':
            if file_count == 1:
                return '1 file'
            if file_count:
                return f'{file_count} files'
            return 'no files'
        if source_tool == 'grep' and output_mode == 'count':
            if match_count:
                return f'{match_count} total matches'
            return 'no matches'
        if match_count and file_count:
            return f'{match_count} matches · {file_count} files'
        if match_count:
            return f'{match_count} matches'
        return 'no matches'

    @staticmethod
    def _build_search_results_extra_lines(
        query: str,
        result_lines: list[str] | None,
        file_list: list[tuple[str, int]] | None,
        file_count: int,
        match_count: int,
        *,
        source_tool: str = 'search',
    ) -> list[ActivityLine]:
        extra_lines: list[ActivityLine] = []
        if result_lines and source_tool not in {'glob', 'find_symbols'}:
            from backend.cli.tool_display.renderers.search import (
                render_search_results,
            )

            rich_lines = render_search_results(
                '\n'.join(result_lines),
                query=query,
                max_files=10,
                max_lines_per_file=4,
            )
            for rl in rich_lines:
                extra_lines.append(ActivityLine(rl, indent=0))
            return extra_lines
        if result_lines and source_tool == 'find_symbols':
            for line in result_lines[:10]:
                extra_lines.append(
                    ActivityLine(
                        f'• {line}',
                        style=NAVY_TEXT_MUTED,
                        indent=1,
                    )
                )
            if len(result_lines) > 10:
                extra_lines.append(
                    ActivityLine(
                        f'... {len(result_lines) - 10} more symbols',
                        style=NAVY_TEXT_DIM,
                        indent=1,
                    )
                )
            return extra_lines
        if not file_list:
            return extra_lines
        max_displayed = 10
        if source_tool == 'glob':
            for filepath, _count in file_list[:max_displayed]:
                extra_lines.append(
                    ActivityLine(
                        f'• {filepath}',
                        style=NAVY_TEXT_MUTED,
                        indent=1,
                    )
                )
            total_displayed = len(file_list[:max_displayed])
            if file_count > total_displayed:
                remaining_files = file_count - total_displayed
                extra_lines.append(
                    ActivityLine(
                        f'... {remaining_files} more files',
                        style=NAVY_TEXT_DIM,
                        indent=1,
                    )
                )
            return extra_lines
        for filepath, count in file_list:
            extra_lines.append(
                ActivityLine(
                    f'• {filepath} ({count} matches)',
                    style=NAVY_TEXT_MUTED,
                    indent=1,
                )
            )
        total_displayed = len(file_list)
        if file_count > total_displayed:
            remaining_files = file_count - total_displayed
            remaining_matches = match_count - sum(c for _, c in file_list)
            extra_lines.append(
                ActivityLine(
                    f'... {remaining_files} more files, {remaining_matches} matches',
                    style=NAVY_TEXT_DIM,
                    indent=1,
                )
            )
        return extra_lines

    @staticmethod
    def search_results(
        query: str,
        match_count: int = 0,
        file_count: int = 0,
        file_list: list[tuple[str, int]] | None = None,
        result_lines: list[str] | None = None,
        scope: str = '',
        *,
        source_tool: str = 'search',
        detail: str | None = None,
        meta_lines: list[str] | None = None,
        output_mode: str | None = None,
    ) -> ActivityCard:
        """Create an activity card for search results.

        Args:
            query: The search pattern
            match_count: Total number of matches
            file_count: Total number of files with matches
            file_list: List of (filepath, match_count) tuples for display
            result_lines: Raw ripgrep-style result lines (file:line:content)
            scope: Optional search path scope (e.g. 'src/runtime')
            source_tool: Tool-specific card preset (``grep``, ``glob``, etc.)
            detail: Optional override for the collapsed detail text
            meta_lines: Optional metadata shown in the expanded card footer
            output_mode: Grep output mode for tailored collapsed summaries
        """
        badge_category, title, verb = _SEARCH_CARD_PRESETS.get(
            source_tool, _SEARCH_CARD_PRESETS['search']
        )
        if detail is None:
            quoted = f'"{query}"'
            detail = f'{quoted} in {scope}' if scope else quoted
        secondary = _ExplorationMixin._build_search_results_secondary(
            match_count,
            file_count,
            source_tool=source_tool,
            output_mode=output_mode,
        )
        extra_lines = _ExplorationMixin._build_search_results_extra_lines(
            query,
            result_lines,
            file_list,
            file_count,
            match_count,
            source_tool=source_tool,
        )
        has_results = bool(match_count or file_count)

        return ActivityCard(
            verb=verb,
            detail=detail,
            badge_category=badge_category,
            title=title,
            secondary=secondary,
            secondary_kind='ok' if has_results else 'neutral',
            extra_lines=extra_lines,
            meta_lines=list(meta_lines or []),
            is_collapsible=bool(extra_lines),
        )

    @staticmethod
    def _build_read_symbols_secondary(
        results: list[dict[str, object]],
    ) -> str:
        if not results:
            return 'no symbols'
        statuses: dict[str, int] = {}
        for item in results:
            status = str(item.get('status') or 'unknown')
            statuses[status] = statuses.get(status, 0) + 1
        if len(statuses) == 1:
            status, count = next(iter(statuses.items()))
            label = 'symbol' if count == 1 else 'symbols'
            return f'{count} {status} {label}'
        parts = [f'{count} {status}' for status, count in sorted(statuses.items())]
        return ' · '.join(parts)

    @staticmethod
    def _build_read_symbols_extra_lines(
        results: list[dict[str, object]],
    ) -> list[ActivityLine]:
        extra_lines: list[ActivityLine] = []
        for item in results[:8]:
            status = str(item.get('status') or 'unknown')
            target = str(
                item.get('qualified_name')
                or item.get('symbol_name')
                or item.get('target')
                or item.get('name')
                or ''
            ).strip()
            path = str(item.get('path') or '').strip()
            if target and path:
                line = f'{status}: {target} ({path})'
            elif target:
                line = f'{status}: {target}'
            else:
                line = status
            extra_lines.append(ActivityLine(line, style=NAVY_TEXT_MUTED, indent=1))
        if len(results) > 8:
            extra_lines.append(
                ActivityLine(
                    f'... {len(results) - 8} more symbols',
                    style=NAVY_TEXT_DIM,
                    indent=1,
                )
            )
        return extra_lines

    @staticmethod
    def read_symbols_results(
        scope: str,
        results: list[dict[str, object]],
        *,
        target_count: int | None = None,
        meta_lines: list[str] | None = None,
    ) -> ActivityCard:
        """Create an activity card for ``read_symbols`` tool results."""
        badge_category, title, verb = _SEARCH_CARD_PRESETS['read_symbols']
        count = len(results) if results else (target_count or 0)
        detail = f'{count} symbol{"s" if count != 1 else ""}'
        if scope:
            detail = f'{detail} in {scope}'
        extra_lines = _ExplorationMixin._build_read_symbols_extra_lines(results)
        secondary = (
            _ExplorationMixin._build_read_symbols_secondary(results)
            if results
            else None
        )
        return ActivityCard(
            verb=verb,
            detail=detail,
            badge_category=badge_category,
            title=title,
            secondary=secondary,
            secondary_kind='ok' if results else 'neutral',
            extra_lines=extra_lines,
            meta_lines=list(meta_lines or []),
            is_collapsible=bool(extra_lines),
        )

    @staticmethod
    def _build_analyze_structure_extra_lines(content: str) -> list[ActivityLine]:
        if not content:
            return []
        lines = content.splitlines()
        extra_lines: list[ActivityLine] = []
        for line in lines[:12]:
            extra_lines.append(
                ActivityLine(
                    line[:120] + ('…' if len(line) > 120 else ''),
                    style=NAVY_TEXT_MUTED,
                    indent=1,
                )
            )
        if len(lines) > 12:
            extra_lines.append(
                ActivityLine(
                    f'... {len(lines) - 12} more lines',
                    style=NAVY_TEXT_DIM,
                    indent=1,
                )
            )
        return extra_lines

    @staticmethod
    def analyze_structure_results(
        command: str,
        path: str,
        content: str,
        *,
        meta_lines: list[str] | None = None,
        error: str = '',
    ) -> ActivityCard:
        """Create an activity card for ``analyze_project_structure`` results."""
        badge_category, title, verb = _SEARCH_CARD_PRESETS['analyze']
        detail = f'{command} · {path}'.strip(' ·')
        extra_lines = _ExplorationMixin._build_analyze_structure_extra_lines(content)
        if error:
            secondary = 'failed'
            secondary_kind = 'err'
        elif content:
            secondary = 'completed'
            secondary_kind = 'ok'
        else:
            secondary = 'no output'
            secondary_kind = 'neutral'
        return ActivityCard(
            verb=verb,
            detail=detail or 'project structure',
            badge_category=badge_category,
            title=title,
            secondary=secondary,
            secondary_kind=secondary_kind,
            extra_lines=extra_lines,
            meta_lines=list(meta_lines or []),
            is_collapsible=bool(extra_lines),
        )
