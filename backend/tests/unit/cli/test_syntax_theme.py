"""Unit tests for Grinta syntax theme and streaming markdown prep."""

from __future__ import annotations

import re
from pathlib import Path

from rich.console import Console
from rich.markdown import Markdown
from rich.syntax import PygmentsSyntaxTheme, Syntax
from rich.theme import Theme

from backend.cli.syntax_theme import (
    GRINTA_SYNTAX_COLORS,
    get_grinta_pygments_style,
    get_grinta_rich_syntax_theme,
    invalidate_grinta_syntax_theme_cache,
    resolve_syntax_colors,
)
from backend.cli.theme import CLR_REASONING_SNAP, grinta_rich_theme_styles
from backend.cli.tui.renderer.prep import (
    prep_markdown,
    prep_streaming_renderable,
    streaming_render_interval,
)


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
        for _text, style, _ in console.render(renderable, console.options.update_width(80))
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


def test_streaming_render_interval_shortens_in_code_fence():
    assert streaming_render_interval('plain prose') == 0.2
    assert streaming_render_interval('`x`') == 0.12
    assert streaming_render_interval('```python\nx') == 0.08
