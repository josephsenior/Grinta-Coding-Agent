"""Shared helpers and presets for unified activity rendering."""

from __future__ import annotations

import re

from pygments.lexers import guess_lexer_for_filename
from pygments.util import ClassNotFound
from rich.text import Text

def _strip_ansi(text: str) -> str:
    """Strip ANSI escape sequences using Rich's parser (handles all ECMA-48 sequences)."""
    if not text:
        return text
    return Text.from_ansi(text).plain


_ERROR_HEAVY_PATTERN = re.compile(
    r'(?im)\b('
    r'error|errors|exception|traceback|failed|failure|panic|fatal|assertionerror|'
    r'validation|invalid|permission denied|not found|syntaxerror|typeerror|'
    r'<<<<<<<|=======|>>>>>>>'
    r')\b'
)


def _looks_error_heavy(text: str | None) -> bool:
    if not text:
        return False
    return bool(_ERROR_HEAVY_PATTERN.search(text))


# Maps a search ``source_tool`` value to the (badge_category, title, verb)
# used by the activity card.  Dedicated tools (``grep``, ``glob``) get their
# own categories; anything else (including the legacy generic ``search``
# source) falls back to the unified search card.
_SEARCH_CARD_PRESETS: dict[str, tuple[str, str, str]] = {
    'grep': ('grep', 'Grep', 'Grepped'),
    'glob': ('glob', 'Glob', 'Globbed'),
    'search': ('search', 'Search', 'Searched'),
    'find_symbols': ('find_symbols', 'Find Symbols', 'Found'),
    'read_symbols': ('read_symbols', 'Read Symbols', 'Read'),
    'analyze': ('analyze', 'Analyze', 'Analyzed'),
}

_WEB_MCP_KINDS: dict[str, str] = {
    'web_search_exa': 'web_search',
    'web_fetch_exa': 'web_fetch',
    '__native_web_fetch__': 'web_fetch',
    'fetch': 'web_fetch',
}

_WEB_CARD_PRESETS: dict[str, tuple[str, str, str]] = {
    'web_search': ('web_search', 'Web Search', 'Searched'),
    'web_fetch': ('web_fetch', 'Web Fetch', 'Fetched'),
}

_BROWSER_OUTCOMES: dict[str, str] = {
    'navigate': 'loaded',
    'screenshot': 'captured',
    'snapshot': 'ready',
    'click': 'clicked',
    'type': 'typed',
    'browse': 'done',
    'start': 'started',
    'close': 'closed',
}


def _exploration_meta_line(tokens: list[str]) -> list[str]:
    """Return a single meta row line when any tokens are present."""
    cleaned = [token for token in tokens if token]
    if not cleaned:
        return []
    return [' · '.join(cleaned)]


def _extract_search_query(command: str) -> str:
    """Extract the search query/pattern from a grep/glob command."""
    # Try to extract quoted pattern: rg "pattern" or grep 'pattern'
    match = re.search(r'(?:rg|grep)\s+[\'"]([^\'"]+)[\'"]', command)
    if match:
        return match.group(1)

    # Try to extract unquoted pattern: rg pattern or grep pattern
    match = re.search(r'(?:rg|grep)\s+(\S+)', command)
    if match:
        return match.group(1)

    # PowerShell Get-ChildItem with filter
    match = re.search(r'-Filter\s+[\'"]([^\'"]+)[\'"]', command)
    if match:
        return match.group(1)

    # Fallback: return first meaningful argument
    parts = command.split()
    for part in parts[1:]:
        if not part.startswith('-') and part not in ('|', 'rg', 'grep'):
            return part[:50]

    return command[:50]


def _lexer_for_path(path: str) -> str | None:
    """Return a Pygments lexer name for ``path`` based on its extension.

    Determined entirely from the filename — no content is inspected, so the
    result is identical for the same path regardless of body. Returns
    ``None`` for paths with no recognised extension.
    """
    if not path:
        return None
    try:
        lexer = guess_lexer_for_filename(path, '')
    except ClassNotFound:
        return None
    if lexer.name.lower() in {'text', 'text only', 'plain text'}:
        return None
    return lexer.name
