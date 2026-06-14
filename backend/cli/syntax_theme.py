"""Shared Rich/Textual syntax highlighting theme for Grinta.

Syntax colors are defined as named tokens in :data:`GRINTA_SYNTAX_COLORS`.
Override any token at runtime with ``GRINTA_SYNTAX_<TOKEN>`` env vars, e.g.
``GRINTA_SYNTAX_KEYWORD=#ff0000``.
"""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Any

from rich.syntax import PygmentsSyntaxTheme, SyntaxTheme
from rich.terminal_theme import TerminalTheme

from backend.cli.theme import NAVY_BG as _NAVY_BG_DEFAULT

# Named syntax palette — extend here to customize highlighting across CLI/TUI.
GRINTA_SYNTAX_COLORS: dict[str, str] = {
    'background': '#07101d',
    'highlight': '#17233a',
    'text': '#d7e2f2',
    'comment': '#71809c',
    'comment_preproc': '#b997ff',
    'keyword': '#7dcfff',
    'keyword_constant': '#f6c177',
    'keyword_declaration': '#5eead4',
    'keyword_namespace': '#91abec',
    'keyword_pseudo': '#c792ea',
    'keyword_type': '#4fd6be',
    'name': '#d7e2f2',
    'name_attribute': '#a6e3ff',
    'name_builtin': '#5eead4',
    'name_builtin_pseudo': '#c792ea',
    'name_class': '#ffd580',
    'name_constant': '#f6c177',
    'name_decorator': '#b997ff',
    'name_entity': '#ff9a9a',
    'name_exception': '#ff9a9a',
    'name_function': '#82aaff',
    'name_function_magic': '#5eead4',
    'name_label': '#ffd580',
    'name_namespace': '#91abec',
    'name_property': '#a6e3ff',
    'name_tag': '#5eead4',
    'name_variable': '#e9e9e9',
    'name_variable_class': '#f6c177',
    'name_variable_global': '#f6c177',
    'literal_date': '#ffcb8b',
    'string': '#b9f27c',
    'string_affix': '#ffcb8b',
    'string_delimiter': '#8f9fc1',
    'string_doc': '#8f9fc1',
    'string_escape': '#ffb86c',
    'string_interpol': '#82aaff',
    'string_regex': '#5eead4',
    'string_symbol': '#ffcb8b',
    'number': '#ffcb8b',
    'operator': '#c8d3f5',
    'operator_word': '#7dcfff',
    'punctuation': '#7f8aa3',
    'generic_deleted': '#ff8f8f',
    'generic_inserted': '#7de6a1',
    'generic_heading': '#91abec',
    'generic_output': '#8f9fc1',
    'generic_prompt': '#91abec',
    'generic_error': '#ff8f8f',
    'error': '#ff8f8f',
    'inline_code_fg': '#d7e2f2',
    'inline_code_bg': '#101829',
    'whitespace': '#4f5f7d',
}

_SYNTAX_ENV_PREFIX = 'GRINTA_SYNTAX_'


def resolve_syntax_colors() -> dict[str, str]:
    """Return the active syntax palette with optional env overrides."""
    colors = dict(GRINTA_SYNTAX_COLORS)
    for key in colors:
        raw = os.getenv(f'{_SYNTAX_ENV_PREFIX}{key.upper()}')
        if raw and raw.strip():
            colors[key] = raw.strip()
    return colors


def _italic(color: str) -> str:
    return f'{color} italic'


def _bg(color: str, background: str) -> str:
    return f'{color} bg:{background}'


@lru_cache(maxsize=1)
def build_grinta_pygments_style() -> type:
    """Build a Pygments Style class from :func:`resolve_syntax_colors`."""
    from pygments.style import Style
    from pygments.token import (
        Comment,
        Error,
        Generic,
        Keyword,
        Literal,
        Name,
        Number,
        Operator,
        Other,
        Punctuation,
        String,
        Text,
        Whitespace,
    )

    c = resolve_syntax_colors()

    class GrintaStyle(Style):
        background_color = c['background']
        highlight_color = c['highlight']

        styles = {
            Text: c['text'],
            Whitespace: c['whitespace'],
            Comment: _italic(c['comment']),
            Comment.Preproc: c['comment_preproc'],
            Comment.Special: c['comment_preproc'],
            Keyword: c['keyword'],
            Keyword.Constant: c['keyword_constant'],
            Keyword.Declaration: c['keyword_declaration'],
            Keyword.Namespace: c['keyword_namespace'],
            Keyword.Pseudo: c['keyword_pseudo'],
            Keyword.Reserved: c['keyword'],
            Keyword.Type: c['keyword_type'],
            Name: c['name'],
            Name.Attribute: c['name_attribute'],
            Name.Builtin: c['name_builtin'],
            Name.Builtin.Pseudo: c['name_builtin_pseudo'],
            Name.Class: c['name_class'],
            Name.Constant: c['keyword_constant'],
            Name.Decorator: c['name_decorator'],
            Name.Entity: c['name_entity'],
            Name.Exception: c['name_exception'],
            Name.Function: c['name_function'],
            Name.Function.Magic: c['name_function_magic'],
            Name.Label: c['name_label'],
            Name.Namespace: c['name_namespace'],
            Name.Other: c['name'],
            Name.Property: c['name_property'],
            Name.Tag: c['name_tag'],
            Name.Variable: c['name_variable'],
            Name.Variable.Class: c['name_variable_class'],
            Name.Variable.Global: c['name_variable_global'],
            Name.Variable.Instance: c['name_variable'],
            Name.Variable.Magic: c['name_decorator'],
            Literal: c['text'],
            Literal.Date: c['literal_date'],
            String: c['string'],
            String.Affix: c['string_affix'],
            String.Backtick: c['string'],
            String.Char: c['string'],
            String.Delimiter: c['string_delimiter'],
            String.Doc: c['string_doc'],
            String.Double: c['string'],
            String.Escape: c['string_escape'],
            String.Heredoc: c['string'],
            String.Interpol: c['string_interpol'],
            String.Other: c['string'],
            String.Regex: c['string_regex'],
            String.Single: c['string'],
            String.Symbol: c['string_symbol'],
            Number: c['number'],
            Number.Bin: c['number'],
            Number.Float: c['number'],
            Number.Hex: c['number'],
            Number.Integer: c['number'],
            Number.Integer.Long: c['number'],
            Number.Oct: c['number'],
            Operator: c['operator'],
            Operator.Word: c['operator_word'],
            Punctuation: c['punctuation'],
            Generic.Deleted: c['generic_deleted'],
            Generic.Emph: _italic(c['text']),
            Generic.Error: c['generic_error'],
            Generic.Heading: c['generic_heading'],
            Generic.Inserted: c['generic_inserted'],
            Generic.Output: c['generic_output'],
            Generic.Prompt: c['generic_prompt'],
            Generic.Strong: c['text'],
            Generic.Subheading: c['generic_heading'],
            Generic.Traceback: c['generic_error'],
            Error: _bg(c['error'], '#2e0d0d'),
            Other: c['text'],
        }

    return GrintaStyle


def get_grinta_pygments_style() -> type:
    """Return the cached Grinta Pygments style class."""
    return build_grinta_pygments_style()


@lru_cache(maxsize=1)
def get_grinta_rich_syntax_theme() -> SyntaxTheme:
    """Return a cached Rich SyntaxTheme backed by the Grinta Pygments style."""
    return PygmentsSyntaxTheme(get_grinta_pygments_style())


@lru_cache(maxsize=1)
def get_grinta_terminal_theme() -> TerminalTheme:
    """Textual ANSI remap aligned with the syntax palette."""
    c = resolve_syntax_colors()

    def _rgb(hex_color: str) -> tuple[int, int, int]:
        value = hex_color.lstrip('#')
        return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)

    bg = _rgb(c['background'])
    fg = _rgb(c['text'])
    return TerminalTheme(
        bg,
        fg,
        [
            (26, 26, 26),
            _rgb(c['generic_error']),
            _rgb(c['generic_inserted']),
            _rgb(c['keyword_constant']),
            _rgb(c['keyword']),
            _rgb(c['name_decorator']),
            _rgb(c['name_function_magic']),
            _rgb(c['punctuation']),
        ],
        [
            _rgb(c['generic_error']),
            _rgb(c['generic_inserted']),
            _rgb(c['keyword_constant']),
            _rgb(c['keyword']),
            _rgb(c['name_decorator']),
            _rgb(c['name_function_magic']),
            _rgb(c['text']),
        ],
    )


# Backward-compatible default for GrintaTUIApp.ansi_theme_dark
GRINTA_TERMINAL_THEME = get_grinta_terminal_theme()


def grinta_syntax_kwargs(*, background_color: str = _NAVY_BG_DEFAULT) -> dict[str, Any]:
    """Common kwargs for Rich ``Syntax`` renderables."""
    return {
        'theme': get_grinta_rich_syntax_theme(),
        'background_color': background_color,
    }


def inline_code_style() -> str:
    """Rich style for inline ``code`` spans during streaming markdown."""
    c = resolve_syntax_colors()
    return f"{c['inline_code_fg']} on {c['inline_code_bg']}"


def invalidate_grinta_syntax_theme_cache() -> None:
    """Clear cached theme objects (tests or hot reload)."""
    get_grinta_rich_syntax_theme.cache_clear()
    build_grinta_pygments_style.cache_clear()
    get_grinta_terminal_theme.cache_clear()
