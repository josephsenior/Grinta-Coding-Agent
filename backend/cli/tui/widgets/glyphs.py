"""Glyph table for the TUI.

Single source of truth for iconography. When accessible mode (or
``GRINTA_ASCII=1``) is active, returns ASCII-friendly alternates
instead of Unicode symbols so the TUI renders correctly in any
terminal/encoding.

The mapping is intentionally conservative: it covers the symbols that
already appear in the TUI and gives each an obvious ASCII twin. New
symbols should be added here, not scattered as raw literals.
"""

from __future__ import annotations

from backend.cli.tui._a11y import ascii_glyphs_enabled

# Scan-line / sidebar / status iconography
_GLYPHS: dict[str, str] = {
    # Scan-line state indicators
    '✓': '+',  # done
    '✗': 'x',  # failed
    '⚠': '!',  # warning
    '●': '*',  # running / sidebar bullet
    '○': 'o',  # idle / sidebar bullet dim
    '◌': 'o',  # waiting alternate
    '◆': 'o',  # sidebar dap icon
    '⤢': '[+]',  # detail button
    '◎': '@',  # open / focus
    '↳': '->',  # orient subtree arrow
    '▸': '>',  # collapsed caret
    '▾': 'v',  # expanded caret
    '⌁': '~',  # live indicator
    '⎇': '#',  # branch alternate
    '⇢': '->',  # arrow
    '⊛': '*',  # highlight
    'ƒ': 'f',  # function glyph
    '⊢': '|',  # rule
    '≡': '=',  # equals
    '⊞': '#',  # grid
    '▣': '#',  # tasks
    '⬡': '#',  # MCP
    '◈': '#',  # LSP
    '✦': '*',  # Skills
    '⟳': '*',  # spinner
    '▰': '#',  # progress fill
    '▱': '-',  # progress empty
    '→': '->',  # arrow
    '↶': '<-',  # undo
    '↲': '->',  # return / enter
    '⏸': '||',  # pause
    '↩': '<-',  # enter alt
    '·': '.',  # middle dot
    '↓': 'v',  # down arrow
    '↑': '^',  # up arrow
    '│': '|',  # vertical bar
    '─': '-',  # horizontal bar
    '┌': '+',  # box top-left
    '┐': '+',  # box top-right
    '└': '+',  # box bottom-left
    '┘': '+',  # box bottom-right
    # Markers from theme/tokens.py
    '❯': '>',  # prompt
}


def glyph(unicode_char: str, host: object | None = None) -> str:
    """Return the active glyph for *unicode_char* honoring accessible mode.

    If the unicode char isn't in the table, it is returned as-is so a new
    symbol can be used temporarily before being added here.
    """
    if not ascii_glyphs_enabled(host):
        return unicode_char
    return _GLYPHS.get(unicode_char, unicode_char)


def mark_ok(host: object | None = None) -> str:
    return glyph('✓', host)


def mark_err(host: object | None = None) -> str:
    return glyph('✗', host)


def mark_warn(host: object | None = None) -> str:
    return glyph('⚠', host)


def mark_info(host: object | None = None) -> str:
    return glyph('●', host)


def mark_prompt(host: object | None = None) -> str:
    return glyph('❯', host)
