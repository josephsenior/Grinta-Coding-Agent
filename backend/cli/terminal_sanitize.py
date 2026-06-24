"""Shared terminal escape-sequence sanitization for CLI surfaces.

Used by the TUI and REPL to strip host-injected CSI/OSC leaks (mouse reports,
selection noise, ConPTY artifacts) before display or agent submission.
"""

from __future__ import annotations

import re

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
# SGR mouse reports (with or without ESC / ``<`` prefix).  Hosts may leak
# 2–5 numeric fields before the trailing ``m``/``M`` (Windows Terminal / ConPTY).
_MOUSE_REPORT_RE = re.compile(r'(?:\x1b)?\[(?:<)?\d{1,7}(?:;\d{1,7}){1,4}[mM]')
# Trailing fragment of a mouse report split across PTY read chunks.
_INCOMPLETE_MOUSE_TAIL_RE = re.compile(
    r'(?:\x1b)?\[(?:<)?\d{1,7}(?:;\d{1,7}){0,4};?\d{0,7}$'
)
# Fast gate for polling sanitizers — avoid regex on every keystroke.
_MOUSE_LEAK_QUICK_RE = re.compile(r'(?:\x1b)?\[(?:<)?\d{1,7};')


def split_trailing_incomplete_mouse_artifact(text: str) -> tuple[str, str]:
    """Hold a partial ``[555;117;`` tail until the next PTY chunk completes it."""
    if not text or text.endswith(('m', 'M')):
        return text, ''
    match = _INCOMPLETE_MOUSE_TAIL_RE.search(text)
    if match is None:
        return text, ''
    return text[: match.start()], match.group(0)


def strip_leaked_terminal_artifacts(text: str) -> str:
    """Remove terminal escape/CSI leaks the host injects (e.g. after Ctrl+C + selection)."""
    if not text:
        return text
    out = text
    for _ in range(16):
        prev = out
        out = _CSI_OSC_DCS.sub('', out)
        out = _MOUSE_REPORT_RE.sub('', out)
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


def looks_like_terminal_leak_fragment(text: str) -> bool:
    """True when the buffer likely contains host-injected mouse/CSI noise."""
    sample = text or ''
    if not sample or '[' not in sample:
        return False
    return bool(_MOUSE_LEAK_QUICK_RE.search(sample))


def sanitize_prompt_input_text(text: str) -> str:
    """Normalize user input: strip terminal leaks; drop pure-noise buffers."""
    cleaned = strip_leaked_terminal_artifacts(text)
    if looks_like_terminal_selection_noise(text):
        return ''
    return cleaned
