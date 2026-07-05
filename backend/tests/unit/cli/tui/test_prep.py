"""Unit tests for TUI render prep helpers."""

from __future__ import annotations

from rich.syntax import Syntax

from backend.cli.tui.renderer.prep import (
    StreamingRenderState,
    _loosen_markdown_spacing,
    prep_markdown,
    prep_streaming_renderable_incremental,
)


def test_loosen_markdown_spacing_adds_paragraph_gap() -> None:
    text = 'First paragraph.\n\nSecond paragraph.'
    loosened = _loosen_markdown_spacing(text)
    assert loosened.count('\n') > text.count('\n')


def test_loosen_markdown_spacing_preserves_code_fences() -> None:
    text = 'Intro\n\n```python\na = 1\n\nb = 2\n```\n\nOutro'
    loosened = _loosen_markdown_spacing(text)
    assert '```python\na = 1\n\nb = 2\n```' in loosened


def test_prep_markdown_accepts_loosened_text() -> None:
    rendered = prep_markdown('Hello\n\nWorld')
    assert rendered is not None


def test_prep_streaming_renderable_uses_full_markdown_for_prose() -> None:
    from rich.markdown import Markdown

    from backend.cli.tui.renderer.prep import prep_streaming_renderable

    renderable = prep_streaming_renderable('**bold** and plain prose')
    assert isinstance(renderable, Markdown)


def test_incremental_streaming_freezes_complete_fences() -> None:
    first = 'Intro\n\n```python\nprint(1)\n```\n'
    second = first + 'More\n\n```python\nprint(2)\n```\n'

    _, state = prep_streaming_renderable_incremental(first, None)
    first_upto = state.committed_upto
    assert first_upto > 0
    assert any(isinstance(part, Syntax) for part in state.committed_parts)

    _renderable, state = prep_streaming_renderable_incremental(second, state)
    assert state.committed_upto >= first_upto
    frozen_syntax = [
        part for part in state.committed_parts if isinstance(part, Syntax)
    ]
    assert len(frozen_syntax) == 2
