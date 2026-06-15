"""Headless TUI — theme."""

from backend.tests.unit.cli.tui import _shared
from backend.tests.unit.cli.tui._shared import *  # noqa: F403

for _name in dir(_shared):
    if _name.startswith('_') and not _name.startswith('__'):
        globals()[_name] = getattr(_shared, _name)


def test_grinta_rich_theme_overrides_inline_markdown_code(monkeypatch):
    monkeypatch.delenv('NO_COLOR', raising=False)
    monkeypatch.delenv('GRINTA_NO_COLOR', raising=False)

    style = grinta_rich_theme_styles()['markdown.code']

    assert 'cyan' not in style.lower()
    assert 'magenta' not in style.lower()
    assert '#101829' in style
