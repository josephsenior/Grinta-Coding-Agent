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

from backend.cli.syntax_theme import get_grinta_rich_syntax_theme, grinta_syntax_kwargs
from backend.cli.theme import NAVY_BG, NAVY_TEXT_PRIMARY
from backend.cli.tui._app_helpers import _encode_unified_diff_text

_COMPLETE_FENCE_RE = re.compile(r'```([^\n`]*)\n(.*?)```', re.DOTALL)
_OPEN_FENCE_RE = re.compile(r'```([^\n`]*)\n(.*)$', re.DOTALL)


@dataclass(frozen=True)
class RenderArtifact:
    """Pre-built render payload for a ledger event."""

    event_id: int
    renderable: Any
    measured_height: int = 1


def prep_markdown(text: str) -> Markdown:
    theme = get_grinta_rich_syntax_theme()
    return Markdown(
        text,
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


def prep_streaming_renderable(text: str) -> Any:
    """Best-effort highlighted renderable for in-flight assistant markdown.

    Complete fenced code blocks are highlighted immediately. An open trailing
    fence is highlighted as it grows. Other markdown is rendered when cheap.
    """
    content = text or ''
    if not content.strip():
        return Text('')

    if '```' not in content:
        if len(content) < 600 and any(
            marker in content for marker in ('**', '__', '`', '\n#', '\n- ', '\n* ')
        ):
            return prep_markdown(content)
        return Text(content, style=NAVY_TEXT_PRIMARY)

    parts: list[Any] = []
    pos = 0
    for match in _COMPLETE_FENCE_RE.finditer(content):
        before = content[pos : match.start()]
        if before.strip():
            parts.append(prep_markdown(before))
        parts.append(_syntax_block(match.group(2), match.group(1)))
        pos = match.end()

    tail = content[pos:]
    open_fence = _OPEN_FENCE_RE.search(tail) if '```' in tail else None
    if open_fence is not None:
        before = tail[: open_fence.start()]
        if before.strip():
            parts.append(prep_markdown(before))
        parts.append(_syntax_block(open_fence.group(2), open_fence.group(1)))
    elif tail.strip():
        parts.append(prep_markdown(tail))

    if not parts:
        return Text(content, style=NAVY_TEXT_PRIMARY)
    if len(parts) == 1:
        return parts[0]
    return Group(*parts)


def prep_unified_diff_text(diff_text: str) -> str:
    return _encode_unified_diff_text(diff_text)


def prep_git_diff_subprocess(workspace: Path, clean_path: str) -> str | None:
    from backend.cli.tui._app_renderer_event_diff import _try_git_diff_subprocess

    return _try_git_diff_subprocess(workspace, clean_path)


async def prep_markdown_async(text: str) -> Markdown:
    return await asyncio.to_thread(prep_markdown, text)


async def prep_streaming_renderable_async(text: str) -> Any:
    return await asyncio.to_thread(prep_streaming_renderable, text)


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
