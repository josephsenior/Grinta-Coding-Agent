"""Shared Rich/Textual syntax highlighting theme for Grinta."""

from __future__ import annotations

from functools import lru_cache

from rich.syntax import PygmentsSyntaxTheme, SyntaxTheme
from rich.terminal_theme import TerminalTheme

from backend.cli.theme import NAVY_BG, get_grinta_pygments_style

# Textual remaps system/ANSI colors through ansi_theme_dark (default: MONOKAI).
# Use Grinta-aligned truecolor mapping so incidental ANSI paths match our palette.
GRINTA_TERMINAL_THEME = TerminalTheme(
    (6, 10, 20),
    (233, 233, 233),
    [
        (26, 26, 26),
        (253, 131, 131),  # fd8383 err
        (84, 239, 174),  # 54efae ok
        (246, 255, 143),  # f6ff8f warn
        (145, 171, 236),  # 91abec brand
        (199, 146, 234),  # c792ea
        (79, 214, 190),  # 4fd6be
        (150, 154, 173),  # 969aad muted
    ],
    [
        (253, 131, 131),
        (84, 239, 174),
        (246, 255, 143),
        (145, 171, 236),
        (199, 146, 234),
        (79, 214, 190),
        (233, 233, 233),
    ],
)


@lru_cache(maxsize=1)
def get_grinta_rich_syntax_theme() -> SyntaxTheme:
    """Return a cached Rich SyntaxTheme backed by the Grinta Pygments style."""
    return PygmentsSyntaxTheme(get_grinta_pygments_style())


def grinta_syntax_kwargs(*, background_color: str = NAVY_BG) -> dict:
    """Common kwargs for Rich ``Syntax`` renderables."""
    return {
        'theme': get_grinta_rich_syntax_theme(),
        'background_color': background_color,
    }


def invalidate_grinta_syntax_theme_cache() -> None:
    """Clear cached theme objects (tests or hot reload)."""
    get_grinta_rich_syntax_theme.cache_clear()
