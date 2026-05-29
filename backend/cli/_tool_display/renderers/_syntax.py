"""Syntax highlighting helpers for renderers."""

from __future__ import annotations

import re
from typing import Any

from rich.text import Text

from backend.cli.theme import get_grinta_pygments_style


def highlight_code_blocks(text: str) -> list[Any]:
    """Split text on markdown code fences, rendering code blocks with Syntax.

    Returns a list of Rich renderables (``Text`` for prose, ``Syntax`` for code).
    Falls back to returning ``[Text(text)]`` when no fences are found.
    """
    from rich.syntax import Syntax

    parts: list[Any] = []
    pattern = re.compile(r'```(\w*)\n(.*?)```', re.DOTALL)
    last = 0
    for m in pattern.finditer(text):
        if m.start() > last:
            parts.append(Text(text[last : m.start()]))
        lang = m.group(1) or 'text'
        code = m.group(2)
        parts.append(
            Syntax(
                code,
                lang,
                word_wrap=True,
                theme=get_grinta_pygments_style(),
                line_numbers=False,
            )
        )
        last = m.end()
    if last < len(text):
        parts.append(Text(text[last:]))
    return parts if parts else [Text(text)]
