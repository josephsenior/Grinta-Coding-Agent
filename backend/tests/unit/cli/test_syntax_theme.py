"""Unit tests for Grinta syntax theme and streaming markdown prep."""

from __future__ import annotations

from rich.console import Console
from rich.markdown import Markdown
from rich.syntax import PygmentsSyntaxTheme, Syntax

from backend.cli.syntax_theme import get_grinta_rich_syntax_theme
from backend.cli.tui._render_prep import prep_markdown, prep_streaming_renderable


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
    assert '91abec' in color
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
    assert any('91abec' in color for color in colors)
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
