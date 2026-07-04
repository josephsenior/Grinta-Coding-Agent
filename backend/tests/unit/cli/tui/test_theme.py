"""Headless TUI — theme."""

from backend.tests.unit.cli.tui._shared import grinta_rich_theme_styles


def test_grinta_rich_theme_overrides_inline_markdown_code(monkeypatch):
    monkeypatch.delenv('NO_COLOR', raising=False)
    monkeypatch.delenv('GRINTA_NO_COLOR', raising=False)

    style = grinta_rich_theme_styles()['markdown.code']

    assert 'cyan' not in style.lower()
    assert 'magenta' not in style.lower()
    assert '#101829' in style
