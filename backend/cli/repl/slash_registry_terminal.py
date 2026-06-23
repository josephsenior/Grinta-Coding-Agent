"""Terminal escape-sequence cleanup for the REPL prompt buffer.

The host terminal sometimes leaks control sequences (CSI / OSC / orphan
bracket-parameter chunks) into the prompt line buffer, especially after
Ctrl+C plus a selection on Windows Terminal / ConPTY. These helpers
strip the leaks in two ways:

* :func:`strip_leaked_terminal_artifacts` — pure string cleanup, used
  on submit and as a building block for live filtering;
* :func:`looks_like_terminal_selection_noise` — heuristic check for a
  whole buffer that is just leaked control noise;
* :func:`attach_prompt_buffer_csi_sanitizer` — live ``on_text_changed``
  hook that rewrites the buffer as the user types, so the user does not
  see leaked bytes in their input.
"""

from __future__ import annotations

import logging
from typing import Any

from backend.cli.terminal_sanitize import (
    looks_like_terminal_selection_noise,
    strip_leaked_terminal_artifacts,
)

logger = logging.getLogger(__name__)

__all__ = [
    'attach_prompt_buffer_csi_sanitizer',
    'looks_like_terminal_selection_noise',
    'strip_leaked_terminal_artifacts',
]


def attach_prompt_buffer_csi_sanitizer(session: Any) -> None:
    """Strip host-injected control-sequence text from the line buffer in real time.

    Without this, leaked ``[nn;...`` sequences from the terminal appear *in* the
    input line; filtering only on submit is too late for the user.
    """
    buf = getattr(session, 'default_buffer', None)
    if buf is None:
        return
    from prompt_toolkit.document import Document

    sinking = [False]

    def _on_text_changed(_: object) -> None:
        if sinking[0]:
            return
        current = buf.text
        clean = strip_leaked_terminal_artifacts(current)
        if clean == current:
            return
        sinking[0] = True
        try:
            pos = min(buf.cursor_position, len(clean))
            buf.document = Document(clean, pos)
        finally:
            sinking[0] = False

    try:
        buf.on_text_changed += _on_text_changed
    except Exception:  # pragma: no cover
        logger.debug('Could not attach CSI sanitizer to prompt buffer', exc_info=True)
