"""Shared helpers and constants for the Grinta native browser module.

Contains module-level utilities that don't fit into a single
mode-specific helper: stderr tracing, URL validation, the
observation-finalize wrapper, DOM-text snapshot chain, and the
typed callable alias used by the structured-extract path.

Extracted from ``backend.execution.browser.grinta_browser`` to keep
that module focused on the public ``GrintaNativeBrowser`` class and
``execute`` dispatcher.
"""

from __future__ import annotations

import os
import re
import sys
from typing import Any, Awaitable, Callable
from urllib.parse import urlparse

StructuredExtractFn = Callable[[str, dict[str, Any], str | None], Awaitable[str]]

_MAX_URL_LEN = 2048
_MAX_TYPE_LEN = 8000

_INDEX_LINE_RE = re.compile(r'^\s*\[\d+\]')


def _browser_trace(msg: str) -> None:
    """Print to stderr when GRINTA_BROWSER_TRACE is set.

    The interactive CLI forces ``app`` logging to ERROR and uses NullHandlers so Rich
    can own the terminal; INFO/WARNING from this module are otherwise invisible.
    """
    raw = os.environ.get('GRINTA_BROWSER_TRACE', '').strip().lower()
    if raw not in ('1', 'true', 'yes', 'on'):
        return
    print(f'[grinta-browser] {msg}', file=sys.stderr, flush=True)


def _validate_http_url(url: str) -> str | None:
    if not url or len(url) > _MAX_URL_LEN:
        return 'Invalid or overly long url.'
    parsed = urlparse(url.strip())
    if parsed.scheme not in ('http', 'https'):
        return 'Only http and https URLs are allowed.'
    if not parsed.netloc:
        return 'URL must include a host.'
    return None


async def _snapshot_text_chain(browser: Any) -> str:
    """Page prose followed by the indexed interactive elements.

    Callers slice this two ways: ``full`` keeps everything, ``interactive``
    keeps only the ``[n]`` lines (see :func:`_interactive_index_lines`).
    Rebuilding the snapshot also refreshes the page-side selector map that
    ``click``/``type`` resolve indices through.
    """
    elements = await browser.snapshot_text()
    prose = await browser.page_text()
    if prose and elements:
        return f'{prose}\n\n{elements}'
    return elements or prose


def _interactive_index_lines(full_text: str) -> list[str]:
    """Lines carrying an ``[n]`` element index."""
    out: list[str] = []
    for line in full_text.splitlines():
        s = line.rstrip()
        if _INDEX_LINE_RE.match(s):
            out.append(s)
    return out


def _finalize_observation(cmd: str, obs: Any) -> Any:
    """Trace right before leaving ``execute`` (stderr when GRINTA_BROWSER_TRACE=1)."""
    _browser_trace(f'execute return command={cmd!r} → {type(obs).__name__}')
    return obs
