"""Off-thread render preparation for TUI hot paths."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from rich.markdown import Markdown

from backend.cli.theme import get_grinta_pygments_style
from backend.cli.tui._app_helpers import _encode_unified_diff_text


@dataclass(frozen=True)
class RenderArtifact:
    """Pre-built render payload for a ledger event."""

    event_id: int
    renderable: Any
    measured_height: int = 1


def prep_markdown(text: str) -> Markdown:
    return Markdown(text, code_theme=get_grinta_pygments_style())


def prep_unified_diff_text(diff_text: str) -> str:
    return _encode_unified_diff_text(diff_text)


def prep_git_diff_subprocess(workspace: Path, clean_path: str) -> str | None:
    from backend.cli.tui._app_renderer_event_diff import _try_git_diff_subprocess

    return _try_git_diff_subprocess(workspace, clean_path)


async def prep_markdown_async(text: str) -> Markdown:
    return await asyncio.to_thread(prep_markdown, text)


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
