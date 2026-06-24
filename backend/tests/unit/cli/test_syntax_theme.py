"""Unit tests for Grinta syntax theme and streaming markdown prep."""

from __future__ import annotations

import asyncio
import re
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from rich.console import Console
from rich.markdown import Markdown
from rich.syntax import PygmentsSyntaxTheme, Syntax
from rich.theme import Theme

from backend.cli.event_rendering.text_utils import sanitize_visible_transcript_text
from backend.cli.theme import CLR_REASONING_SNAP, grinta_rich_theme_styles
from backend.cli.theme.syntax_theme import (
    GRINTA_SYNTAX_COLORS,
    get_grinta_pygments_style,
    get_grinta_rich_syntax_theme,
    invalidate_grinta_syntax_theme_cache,
    resolve_syntax_colors,
)
from backend.cli.tui.renderer.prep import (
    prep_live_response_renderable,
    prep_markdown,
    prep_streaming_renderable,
)
from backend.ledger.action.message import StreamingChunkAction


def _keyword_color(md: Markdown) -> str | None:
    console = Console(force_terminal=True, color_system='truecolor', width=80)
    for text, style, _ in console.render(md, console.options.update_width(80)):
        if text.strip() == 'def' and style and style.color:
            return str(style.color)
    return None


def test_prep_markdown_uses_grinta_syntax_theme_not_monokai():
    sample = """```python
def hello():
    return 1
```"""
    md = prep_markdown(sample)
    theme = md.code_theme
    assert isinstance(theme, PygmentsSyntaxTheme)

    color = _keyword_color(md)
    assert color is not None
    assert '7dcfff' in color
    assert '66d9ef' not in color


def test_prep_streaming_renderable_highlights_open_fence():
    partial = """Explain:

```python
def stream_me():
    ret"""
    renderable = prep_streaming_renderable(partial)
    assert renderable is not None

    console = Console(force_terminal=True, color_system='truecolor', width=80)
    colors = {
        str(style.color)
        for _text, style, _ in console.render(
            renderable, console.options.update_width(80)
        )
        if style and style.color and _text.strip()
    }
    assert any('7dcfff' in color for color in colors)
    assert not any('66d9ef' in color for color in colors)


def test_grinta_rich_syntax_theme_differs_from_monokai():
    code = 'def hello():\n    return 1'
    grinta = Syntax(code, 'python', theme=get_grinta_rich_syntax_theme())
    monokai = Syntax(code, 'python', theme='monokai')
    console = Console(force_terminal=True, color_system='truecolor', width=80)
    options = console.options.update_width(80)

    def colors(syn: Syntax) -> set[str]:
        return {
            str(style.color)
            for _t, style, _ in console.render(syn, options)
            if style and style.color and _t.strip() == 'def'
        }

    assert colors(grinta) != colors(monokai)


def test_syntax_colors_env_override(monkeypatch):
    monkeypatch.setenv('GRINTA_SYNTAX_KEYWORD', '#112233')
    invalidate_grinta_syntax_theme_cache()
    colors = resolve_syntax_colors()
    assert colors['keyword'] == '#112233'
    invalidate_grinta_syntax_theme_cache()
    monkeypatch.delenv('GRINTA_SYNTAX_KEYWORD', raising=False)


def test_syntax_palette_has_extended_tokens():
    assert 'name_function' in GRINTA_SYNTAX_COLORS
    assert 'inline_code_bg' in GRINTA_SYNTAX_COLORS


def test_prep_streaming_inline_code():
    renderable = prep_streaming_renderable('Use `my_func` here')
    console = Console(force_terminal=True, color_system='truecolor', width=80)
    styles = [
        style
        for _t, style, _ in console.render(renderable, console.options.update_width(80))
        if style and _t.strip() == 'my_func'
    ]
    assert any('101829' in str(style) for style in styles)
    assert all(style.bold is not True for style in styles)


def test_prep_streaming_inline_code_can_use_reasoning_base_style():
    renderable = prep_streaming_renderable(
        'Use `my_func` here', base_text_style=CLR_REASONING_SNAP
    )
    console = Console(force_terminal=True, color_system='truecolor', width=80)
    rendered = list(console.render(renderable, console.options.update_width(80)))

    prose_styles = [
        style
        for text, style, _ in rendered
        if style and text.strip() in {'Use', 'here'}
    ]
    code_styles = [
        style for text, style, _ in rendered if style and text.strip() == 'my_func'
    ]

    expected_color = CLR_REASONING_SNAP.split()[-1].lstrip('#')
    assert prose_styles
    assert all(expected_color in str(style.color) for style in prose_styles)
    assert any('101829' in str(style) for style in code_styles)


def test_grinta_syntax_theme_has_no_bold_tokens():
    style_cls = get_grinta_pygments_style()
    assert not any('bold' in value.split() for value in style_cls.styles.values())

    code = 'class Greeter:\n    def hello(self):\n        return "hi"'
    syntax = Syntax(code, 'python', theme=get_grinta_rich_syntax_theme())
    console = Console(force_terminal=True, color_system='truecolor', width=80)
    rendered_styles = [
        style
        for text, style, _ in console.render(syntax, console.options.update_width(80))
        if text.strip() and style is not None
    ]
    assert rendered_styles
    assert all(style.bold is not True for style in rendered_styles)


def test_tui_markdown_theme_disables_rich_default_bold():
    theme = Theme(grinta_rich_theme_styles())
    console = Console(
        force_terminal=True,
        color_system='truecolor',
        width=80,
        theme=theme,
    )
    md = Markdown('# Head\n\n**strong** and `code`')
    rendered_styles = [
        style
        for text, style, _ in console.render(md, console.options.update_width(80))
        if text.strip() and style is not None
    ]
    assert rendered_styles
    assert all(style.bold is not True for style in rendered_styles)


def test_prep_markdown_renderable_applies_grinta_theme():
    md = prep_markdown('# Head\n\n**strong** and `code`')
    console = Console(force_terminal=True, color_system='truecolor', width=80)
    rendered_styles = [
        style
        for text, style, _ in console.render(md, console.options.update_width(80))
        if text.strip() and style is not None
    ]
    assert rendered_styles
    assert all(style.bold is not True for style in rendered_styles)


def test_tui_sources_do_not_request_bold_text():
    tui_root = Path('backend/cli/tui')
    offenders: list[str] = []
    for path in tui_root.rglob('*'):
        if path.suffix not in {'.py', '.tcss'} or 'tests' in path.parts:
            continue
        content = path.read_text(encoding='utf-8')
        if re.search(r'\bbold\b|text-style:\s*bold', content):
            offenders.append(str(path))
    assert offenders == []


@pytest.mark.asyncio
async def test_preprocess_event_async_normalizes_streaming_cache_key() -> None:
    from backend.cli.display.hud import HUDBar
    from backend.cli.display.reasoning_display import ReasoningDisplay
    from backend.cli.tui.app import TUIRenderer
    from backend.cli.tui.renderer.drain import _preprocess_event_async

    raw = 'Here is code:\n```python\ndef foo():\n    return 1'
    norm = sanitize_visible_transcript_text(raw)

    renderer = TUIRenderer(
        console=Console(),
        hud=HUDBar(),
        reasoning=ReasoningDisplay(),
        tui=MagicMock(),
        loop=asyncio.get_running_loop(),
    )

    action = StreamingChunkAction(accumulated=raw, is_final=False)
    await _preprocess_event_async(renderer, action)
    assert norm in renderer._streaming_render_cache


def test_prep_live_response_renderable_styles_markdown_prose() -> None:
    from rich.markdown import Markdown

    renderable = prep_live_response_renderable('**bold** and `code`')
    assert isinstance(renderable, Markdown)


def test_apply_live_response_render_highlights_open_fence_without_deferred_flush():
    from unittest.mock import MagicMock

    from rich.console import Console

    from backend.cli.display.hud import HUDBar
    from backend.cli.display.reasoning_display import ReasoningDisplay
    from backend.cli.tui.app import TUIRenderer

    renderer = TUIRenderer(
        console=Console(),
        hud=HUDBar(),
        reasoning=ReasoningDisplay(),
        tui=MagicMock(),
        loop=MagicMock(),
    )
    widget = MagicMock()
    renderer._live_response_widget = widget

    partial = '```python\ndef stream_me():\n    return 1'
    renderer._apply_live_response_render(partial)

    widget.set_streaming_content.assert_called_once_with(partial)
    widget.set_streaming_text.assert_not_called()


@pytest.mark.asyncio
async def test_live_response_set_streaming_content_highlights_open_fence() -> None:
    from rich.syntax import Syntax
    from textual.app import App, ComposeResult
    from textual.widgets import Static

    from backend.cli.tui.widgets.activity_card import LiveResponse

    class _LiveHost(App):
        def compose(self) -> ComposeResult:
            yield LiveResponse(id='live')

    def _contains_syntax(node: object) -> bool:
        if isinstance(node, Syntax):
            return True
        renderables = getattr(node, 'renderables', None)
        if renderables:
            return any(_contains_syntax(part) for part in renderables)
        return False

    async with _LiveHost().run_test() as pilot:
        await pilot.pause()
        widget = pilot.app.query_one('#live', LiveResponse)
        widget.set_streaming_content('```python\ndef stream_me():\n    return 1')
        content = widget.query_one('#live-content', Static)
        assert _contains_syntax(content.renderable)
