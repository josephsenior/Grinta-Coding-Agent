"""Terminal escape-sequence cleanup.

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
import re
from typing import Any

logger = logging.getLogger(__name__)


# Leaked bracket-param sequences (e.g. Windows Terminal / ConPTY) — often no ESC.
_ORPHAN_BRACKET_CSI = re.compile(
    r'\[+(?:\d+;){2,}[\d;:_\s-]*[OI]?(?=\[|$| |\Z)',
    re.MULTILINE,
)
# Bracketless leaked parameter chunks seen in some ConPTY/Cursor terminals:
# e.g. ``0;1;40;1_0;0;32;1_8;1;32;1_``.
_ORPHAN_PARAM_CHUNK_STREAM = re.compile(
    r'(?<![A-Za-z0-9])(?:\[?(?:\d+;){2,}\d+[OI]?_){2,}',
    re.MULTILINE,
)
_ORPHAN_PARAM_CHUNK_SINGLE = re.compile(
    r'(?<![A-Za-z0-9])\[?(?:\d+;){4,}\d+[OI]?_',
    re.MULTILINE,
)
# Well-formed 7-bit CSI and OSC (bell or ST-terminated).
_CSI_OSC_DCS = re.compile(
    r'(?:\x1B\][^\x07\x1B]*(?:\x07|\x1B\\))'
    r'|(?:\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~]))',
    re.DOTALL,
)


def strip_leaked_terminal_artifacts(text: str) -> str:
    """Remove terminal escape/CSI leaks the host injects (e.g. after Ctrl+C + selection)."""
    if not text:
        return text
    out = text
    for _ in range(16):
        prev = out
        out = _CSI_OSC_DCS.sub('', out)
        out = _ORPHAN_BRACKET_CSI.sub('', out)
        out = _ORPHAN_PARAM_CHUNK_STREAM.sub('', out)
        out = _ORPHAN_PARAM_CHUNK_SINGLE.sub('', out)
        # focus in/out and similar two-letter CSI finals without a leading esc byte
        out = re.sub(r'\[+(?:O|I)+', '', out)
        if out == prev:
            break
    return out


def looks_like_terminal_selection_noise(text: str) -> bool:
    """Best-effort: whole buffer is only leaked terminal control noise."""
    sample = (text or '').strip()
    if len(sample) < 8:
        return False
    cleaned = strip_leaked_terminal_artifacts(sample)
    return not cleaned.strip()


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
