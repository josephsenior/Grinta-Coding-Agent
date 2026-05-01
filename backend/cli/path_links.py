"""OSC-8–friendly link segments for Rich ``Text`` (file and http(s) URIs).

VS Code and other terminals treat Rich hyperlink metadata as Ctrl+Clickable
targets. We resolve workspace-relative paths against :func:`os.getcwd`.
"""

from __future__ import annotations

import re
from pathlib import Path

from rich.style import Style
from rich.text import Text

from backend.cli.theme import STYLE_DEFAULT


def _parse_style(plain_style: str) -> Style:
    return Style.parse(plain_style) if plain_style else Style()


# Likely file paths / URLs — matched in order; URLs first when enabled.
# Windows drive paths, POSIX absolute/relative with slash, or segmented relpaths.
_PATH_RE = re.compile(
    r'(?:'
    r'https?://[^\s<>\[\](){}|·]+'
    r'|[A-Za-z]:[\\/][^|·\n\r<>\[\]"]*'
    r'|(?:\./|\.\./|/)(?:[^|·\n\r<>\[\]"]|/(?![\s|·]))+'
    r'|[\w.-][\w.-]*/(?:[\w.-]+/)*[\w.-]+\.[A-Za-z0-9]{1,8}\b'
    r')'
)


def _strip_trailing_punct(segment: str) -> tuple[str, str]:
    """Separate trailing ``.,;:!?)]}`` from a path-ish token."""
    s = segment
    trail = ''
    while s and s[-1] in '.,;:!?)]}':
        trail = s[-1] + trail
        s = s[:-1]
    return s, trail


def file_uri_for_path(path_str: str) -> str | None:
    """Resolve *path_str* to a ``file://`` URI for terminal hyperlinks, or ``None``."""
    return _to_file_uri(path_str)


def _to_file_uri(path_str: str) -> str | None:
    raw = path_str.strip().strip('\'"')
    if not raw or len(raw) > 4096 or '://' in raw:
        return None
    if not (
        raw.startswith(('/', '\\', '.'))
        or (len(raw) > 1 and raw[1] == ':')
        or '/' in raw
        or '\\' in raw
    ):
        return None
    try:
        p = Path(raw)
        if not p.is_absolute():
            p = Path.cwd() / p
        resolved = p.expanduser().resolve()
        return resolved.as_uri()
    except (OSError, ValueError, RuntimeError):
        return None


def linkify_plain(
    text: str,
    *,
    plain_style: str = STYLE_DEFAULT,
    link_files: bool = True,
    link_urls: bool = False,
) -> Text:
    """Return ``Text`` with hyperlink spans for paths and optionally ``https`` URLs."""
    s = text or ''
    if not s:
        return Text()

    want_url = link_urls
    want_file = link_files
    if not want_url and not want_file:
        return Text(s, style=_parse_style(plain_style))

    base = _parse_style(plain_style)
    out = Text()
    pos = 0
    for m in _PATH_RE.finditer(s):
        start, end = m.start(), m.end()
        if start > pos:
            out.append(s[pos:start], style=base)
        raw_seg = m.group(0)
        seg, trail = _strip_trailing_punct(raw_seg)
        link: str | None = None
        if want_url and seg.lower().startswith(('http://', 'https://')):
            link = seg
        elif want_file and not seg.lower().startswith(('http://', 'https://')):
            link = _to_file_uri(seg)
        if link:
            out.append(seg, style=base.update_link(link))
            if trail:
                out.append(trail, style=base)
        else:
            out.append(raw_seg, style=base)
        pos = end
    if pos < len(s):
        out.append(s[pos:], style=base)
    return out
