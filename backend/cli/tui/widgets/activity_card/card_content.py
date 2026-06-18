"""Extra-content rendering helpers for ActivityCard."""

from __future__ import annotations

import json
from typing import Any

from rich.syntax import Syntax
from textual.widgets import Static

from backend.cli.theme.syntax_theme import get_grinta_rich_syntax_theme
from backend.cli.theme import NAVY_BG, NAVY_TEXT_MUTED
from backend.cli.tui.widgets.activity_card.diff_lines import (
    DiffLine,
    SplitDiffLine,
    _decode_diff_line,
    _decode_split_diff_line,
)


class ActivityCardContentMixin:
    """Syntax highlighting and diff decoding for expanded card bodies."""

    _extra_content: str | None
    _syntax_language: str | None
    _diff_encoded: bool

    def _build_syntax_renderable(
        self,
        content: str,
        language: str,
        *,
        line_numbers: bool = False,
    ) -> Syntax:
        return Syntax(
            content,
            language,
            theme=get_grinta_rich_syntax_theme(),
            background_color=NAVY_BG,
            line_numbers=line_numbers,
            padding=(0, 1),
            word_wrap=True,
        )

    def _is_diff_like_content(self, content: str) -> bool:
        if content.startswith('--- ') or content.startswith('diff --git'):
            return True
        return any(
            line.startswith(('+', '-', '@@'))
            for line in content.splitlines()
            if line and not line.startswith(('+++', '---'))
        )

    def _try_json_syntax(self, content: str) -> Any | None:
        is_json_shape = (content.startswith('{') and content.endswith('}')) or (
            content.startswith('[') and content.endswith(']')
        )
        if not is_json_shape:
            return None
        try:
            json.loads(content)
        except Exception:
            return None
        return self._build_syntax_renderable(content, 'json')

    def _format_plain_content(self, content: str) -> str:
        lines = content.splitlines() or ['']
        styled_lines = [f'[{NAVY_TEXT_MUTED}]{line}[/]' for line in lines]
        return '\n'.join(styled_lines)

    @staticmethod
    def _looks_like_json_buffer(content: str) -> bool:
        stripped = content.strip()
        return stripped.startswith('{') or stripped.startswith('[')

    def _auto_detect_format(self, content: str) -> Any:
        if self._is_diff_like_content(content):
            return self._build_syntax_renderable(content, 'diff', line_numbers=True)
        if self._looks_like_json_buffer(content):
            return self._build_syntax_renderable(content, 'json')
        json_result = self._try_json_syntax(content)
        if json_result is not None:
            return json_result
        if '```' in content or '`' in content:
            from backend.cli.tui.renderer.prep import prep_streaming_renderable

            return prep_streaming_renderable(content, base_text_style=NAVY_TEXT_MUTED)
        return self._format_plain_content(content)

    def _get_formatted_extra_content(self) -> Any:
        content = self._extra_content or ''

        if '[on #' in content:
            return content

        if self._syntax_language:
            return self._build_syntax_renderable(
                content,
                self._syntax_language,
                line_numbers=self._syntax_language == 'diff',
            )

        return self._auto_detect_format(content)

    def _extra_renderables(self) -> list[Any]:
        content = self._extra_content or ''

        if self._diff_encoded:
            from backend.cli.tui.widgets.unified_diff_view import diff_view_from_encoded

            diff_view = diff_view_from_encoded(content)
            if diff_view is not None:
                return [diff_view]

            renderables: list[Any] = []
            for line in content.splitlines():
                split_decoded = _decode_split_diff_line(line)
                if split_decoded is not None:
                    left, right, left_kind, right_kind = split_decoded
                    renderables.append(
                        SplitDiffLine(left, right, left_kind, right_kind)
                    )
                    continue
                decoded = _decode_diff_line(line)
                if decoded is not None:
                    kind, body = decoded
                    renderables.append(DiffLine(body, kind))
                else:
                    renderables.append(DiffLine(line, 'ctx'))
            return renderables or [Static('', id='extra')]

        return [Static(self._get_formatted_extra_content(), id='extra')]
