"""Unit tests for TUI render prep helpers."""

from __future__ import annotations

from backend.cli.tui.renderer.prep import _loosen_markdown_spacing, prep_markdown


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
