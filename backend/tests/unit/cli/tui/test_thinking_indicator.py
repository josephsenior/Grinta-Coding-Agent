"""Unit tests for ThinkingIndicator lightweight highlighting."""

from __future__ import annotations

import pytest
from rich.console import Group
from rich.syntax import Syntax
from rich.text import Text
from textual.app import App, ComposeResult
from textual.widgets import Static

from backend.cli.tui.widgets.activity_card import ThinkingIndicator


class _ThinkingHost(App):
    def compose(self) -> ComposeResult:
        yield ThinkingIndicator(id='thinking')


@pytest.mark.asyncio
async def test_thinking_indicator_finalized_inline_code_uses_lightweight_highlight() -> None:
    app = _ThinkingHost()

    async with app.run_test():
        widget = app.query_one('#thinking', ThinkingIndicator)
        widget.start()
        widget.set_thoughts('Inspect `backend/main.py` before editing.', streaming=False)

        content = widget.query_one('#thinking-content', Static)
        renderable = content.renderable
        assert isinstance(renderable, Group)
        body = renderable.renderables[1]
        assert isinstance(body, Text)
        assert 'backend/main.py' in body.plain


@pytest.mark.asyncio
async def test_thinking_indicator_finalized_fenced_code_uses_syntax() -> None:
    app = _ThinkingHost()

    async with app.run_test():
        widget = app.query_one('#thinking', ThinkingIndicator)
        widget.start()
        widget.set_thoughts('Plan:\n```python\nprint("hi")\n```', streaming=False)

        content = widget.query_one('#thinking-content', Static)
        renderable = content.renderable
        assert isinstance(renderable, Group)
        body = renderable.renderables[1]
        assert isinstance(body, Group)
        assert any(isinstance(part, Syntax) for part in body.renderables)


@pytest.mark.asyncio
async def test_thinking_indicator_plain_prose_stays_flat() -> None:
    app = _ThinkingHost()

    async with app.run_test():
        widget = app.query_one('#thinking', ThinkingIndicator)
        widget.start()
        widget.set_thoughts('Plotting the next move.', streaming=False)

        content = widget.query_one('#thinking-content', Static)
        renderable = content.renderable
        assert isinstance(renderable, Group)
        body = renderable.renderables[1]
        assert isinstance(body, Text)
        assert 'Plotting the next move.' in body.plain
