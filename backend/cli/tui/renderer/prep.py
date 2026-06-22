"""Off-thread render preparation for TUI hot paths."""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from rich.console import Group
from rich.markdown import Markdown
from rich.syntax import Syntax
from rich.text import Text
from rich.theme import Theme

from backend.cli.theme import NAVY_TEXT_PRIMARY, grinta_rich_theme_styles
from backend.cli.theme.syntax_theme import (
    get_grinta_rich_syntax_theme,
    grinta_syntax_kwargs,
    inline_code_style,
)
from backend.cli.tui.helpers import _encode_unified_diff_text

_COMPLETE_FENCE_RE = re.compile(r'```([^\n`]*)\n(.*?)```', re.DOTALL)
_OPEN_FENCE_RE = re.compile(r'```([^\n`]*)\n(.*)$', re.DOTALL)
_OPEN_FENCE_START_RE = re.compile(r'```([^\n`]*)$')
_INLINE_CODE_RE = re.compile(r'`([^`\n]+)`')


class GrintaMarkdown(Markdown):
    def __rich_console__(self, console, options):
        console.push_theme(Theme(grinta_rich_theme_styles()))
        try:
            yield from super().__rich_console__(console, options)
        finally:
            console.pop_theme()


def _prep_inline_code_text(
    text: str, *, base_text_style: str = NAVY_TEXT_PRIMARY
) -> Text:
    """Lightweight inline-code styling without full Markdown parsing."""
    parts: list[Any] = []
    pos = 0
    for match in _INLINE_CODE_RE.finditer(text):
        before = text[pos : match.start()]
        if before:
            parts.append((before, base_text_style))
        parts.append((match.group(1), inline_code_style()))
        pos = match.end()
    tail = text[pos:]
    if tail:
        parts.append((tail, base_text_style))
    if not parts:
        return Text(text, style=base_text_style)
    return Text.assemble(*parts)


def _split_streaming_fences(content: str) -> tuple[list[Any], str, bool]:
    """Parse complete/open fenced blocks from streaming assistant text."""
    parts: list[Any] = []
    pos = 0
    has_open_fence = False

    for match in _COMPLETE_FENCE_RE.finditer(content):
        before = content[pos : match.start()]
        if before.strip():
            parts.append(before)
        parts.append(_syntax_block(match.group(2), match.group(1)))
        pos = match.end()

    tail = content[pos:]
    open_fence = _OPEN_FENCE_RE.search(tail) if '```' in tail else None
    if open_fence is not None:
        before = tail[: open_fence.start()]
        if before.strip():
            parts.append(before)
        parts.append(_syntax_block(open_fence.group(2), open_fence.group(1)))
        has_open_fence = True
    elif tail.strip():
        if _OPEN_FENCE_START_RE.search(tail):
            before = _OPEN_FENCE_START_RE.split(tail, maxsplit=1)[0]
            if before.strip():
                parts.append(before)
            has_open_fence = True
        else:
            parts.append(tail)

    return parts, tail, has_open_fence


def _render_streaming_segment(
    segment: str, *, base_text_style: str = NAVY_TEXT_PRIMARY
) -> Any:
    if not segment.strip():
        return None
    if '`' in segment and '```' not in segment:
        return _prep_inline_code_text(segment, base_text_style=base_text_style)
    if (
        base_text_style == NAVY_TEXT_PRIMARY
        and len(segment) < 600
        and any(
            marker in segment for marker in ('**', '__', '`', '\n#', '\n- ', '\n* ')
        )
    ):
        return prep_markdown(segment)
    if '`' in segment:
        return _prep_inline_code_text(segment, base_text_style=base_text_style)
    return Text(segment, style=base_text_style)


@dataclass(frozen=True)
class RenderArtifact:
    """Pre-built render payload for a ledger event."""

    event_id: int
    renderable: Any
    measured_height: int = 1


def _loosen_markdown_spacing(text: str) -> str:
    """Add a little air between markdown paragraphs (not inside code fences)."""
    if not text.strip():
        return text

    def _expand_paragraph_gaps(segment: str) -> str:
        return re.sub(r'\n{2,}', '\n\n\n', segment)

    parts: list[str] = []
    last = 0
    for match in _COMPLETE_FENCE_RE.finditer(text):
        parts.append(_expand_paragraph_gaps(text[last : match.start()]))
        parts.append(match.group(0))
        last = match.end()
    parts.append(_expand_paragraph_gaps(text[last:]))
    return ''.join(parts)


def prep_markdown(text: str) -> Markdown:
    theme = get_grinta_rich_syntax_theme()
    return GrintaMarkdown(
        _loosen_markdown_spacing(text),
        code_theme=theme,
        inline_code_theme=theme,
    )


def _syntax_block(code: str, language: str) -> Syntax:
    return Syntax(
        code.rstrip('\n'),
        language or 'text',
        word_wrap=True,
        padding=(0, 1),
        **grinta_syntax_kwargs(),
    )


def prep_live_response_renderable(text: str) -> Any:
    """Render in-flight assistant messages with the same richness as finalized rows.

    Prose uses full Markdown (matching :class:`AgentMessage`). Fenced code blocks
    use the streaming fence parser so open blocks still tokenize as tokens arrive.
    """
    content = text or ''
    if not content.strip():
        return Text('')

    if '```' not in content:
        return prep_markdown(content)

    raw_parts, _tail, _has_open = _split_streaming_fences(content)
    parts: list[Any] = []
    for segment in raw_parts:
        if isinstance(segment, Syntax):
            parts.append(segment)
            continue
        if not isinstance(segment, str) or not segment.strip():
            continue
        parts.append(prep_markdown(segment))

    if not parts:
        return Text(content)
    if len(parts) == 1:
        return parts[0]
    return Group(*parts)


def prep_streaming_renderable(
    text: str, *, base_text_style: str = NAVY_TEXT_PRIMARY
) -> Any:
    """Best-effort highlighted renderable for in-flight assistant markdown.

    Complete and in-progress fenced code blocks are highlighted as tokens
    arrive. Inline ``code`` spans get lightweight styling. Full Markdown is
    reserved for short sections or finalized messages — Pygments needs a
    stable buffer, not character-by-character lexer state.
    """
    content = text or ''
    if not content.strip():
        return Text('')

    if '```' not in content:
        if '`' in content:
            return _prep_inline_code_text(content, base_text_style=base_text_style)
        if (
            base_text_style == NAVY_TEXT_PRIMARY
            and len(content) < 600
            and any(
                marker in content for marker in ('**', '__', '`', '\n#', '\n- ', '\n* ')
            )
        ):
            return prep_markdown(content)
        return Text(content, style=base_text_style)

    raw_parts, _tail, _has_open = _split_streaming_fences(content)
    parts: list[Any] = []
    for segment in raw_parts:
        if isinstance(segment, Syntax):
            parts.append(segment)
            continue
        rendered = _render_streaming_segment(segment, base_text_style=base_text_style)
        if rendered is not None:
            parts.append(rendered)

    if not parts:
        return Text(content, style=base_text_style)
    if len(parts) == 1:
        return parts[0]
    return Group(*parts)


def streaming_render_interval(text: str) -> float:
    """Return a shorter paint interval while a fenced code block is open."""
    if '```' in text:
        return 0.08
    if '`' in text:
        return 0.12
    return 0.25


def prep_unified_diff_text(diff_text: str) -> str:
    return _encode_unified_diff_text(diff_text)


def prep_git_diff_subprocess(workspace: Path, clean_path: str) -> str | None:
    from backend.cli.tui.renderer.diff import _try_git_diff_subprocess

    return _try_git_diff_subprocess(workspace, clean_path)


async def prep_markdown_async(text: str) -> Markdown:
    return await asyncio.to_thread(prep_markdown, text)


async def prep_streaming_renderable_async(text: str) -> Any:
    return await asyncio.to_thread(prep_streaming_renderable, text)


async def prep_live_response_renderable_async(text: str) -> Any:
    return await asyncio.to_thread(prep_live_response_renderable, text)


async def prep_unified_diff_text_async(diff_text: str) -> str:
    return await asyncio.to_thread(prep_unified_diff_text, diff_text)


async def prep_git_diff_async(workspace: Path, clean_path: str) -> str | None:
    return await asyncio.to_thread(prep_git_diff_subprocess, workspace, clean_path)


def prep_file_edit_encoded_diff(orch: Any, event: Any) -> str | None:
    encoded = orch._extract_file_edit_group_rows(event)
    if encoded:
        return encoded
    diff_text = orch._extract_file_edit_diff(event)
    if not diff_text:
        return None
    return prep_unified_diff_text(diff_text)


async def prep_file_edit_encoded_diff_async(orch: Any, event: Any) -> str | None:
    return await asyncio.to_thread(prep_file_edit_encoded_diff, orch, event)


# Bounded cache of off-thread-prepared streaming renderables, keyed by the
# accumulated response text. Keeps the Textual event loop free of synchronous
# Pygments/Markdown work for the in-flight assistant response.
_STREAMING_RENDER_CACHE_MAX = 8


def streaming_render_cache_key(text: str) -> str:
    """Stable cache key for an accumulated streaming-response snapshot."""
    return text or ''


async def prep_streaming_response_async(orch: Any, text: str) -> None:
    """Prepare the streaming-response renderable off the UI thread.

    Populates ``orch._streaming_render_cache`` (a dict keyed by the accumulated
    text) so ``_apply_live_response_render`` can reuse it without blocking the
    event loop. Best-effort: failures are swallowed and the synchronous path
    remains the fallback.
    """
    content = text or ''
    if not content.strip():
        return
    cache = getattr(orch, '_streaming_render_cache', None)
    if cache is None:
        cache = {}
        orch._streaming_render_cache = cache
    key = streaming_render_cache_key(content)
    if key in cache:
        return
    try:
        renderable = await asyncio.to_thread(prep_live_response_renderable, content)
    except Exception:
        return
    cache[key] = renderable
    if getattr(orch, '_live_response', '') == content:
        apply = getattr(orch, '_apply_live_response_render', None)
        if callable(apply):
            apply(content, force=True)
    # Bound the cache: streaming text only grows, so the oldest (shortest)
    # snapshots are the safest to drop.
    if len(cache) > _STREAMING_RENDER_CACHE_MAX:
        for stale_key in sorted(cache, key=len)[
            : len(cache) - _STREAMING_RENDER_CACHE_MAX
        ]:
            cache.pop(stale_key, None)
