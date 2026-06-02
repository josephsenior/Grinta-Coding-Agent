"""Utilities for bounded, deduplicated lesson persistence."""

from __future__ import annotations

import re
import time
from difflib import SequenceMatcher
from pathlib import Path

_BULLET_TIMESTAMP_RE = re.compile(r'^\s*-\s*\[[^\]]+\]\s*')
_SEEN_SUFFIX_RE = re.compile(r'\s+\(seen\s+(\d+)x\)\s*$', re.IGNORECASE)
_MD_HEADING_RE = re.compile(r'(?m)^##\s+.+$')
_DEFAULT_SIMILARITY_THRESHOLD = 0.88
_MIN_FUZZY_MATCH_CHARS = 40


def normalize_lesson_text(value: str) -> str:
    """Return a stable comparison key for a lesson-like text blob."""
    text = _BULLET_TIMESTAMP_RE.sub('', value or '')
    text = _SEEN_SUFFIX_RE.sub('', text)
    text = text.casefold()
    text = re.sub(r'[`*_~#>\[\](){},.:;!?-]+', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def lessons_are_similar(
    left: str,
    right: str,
    *,
    threshold: float = _DEFAULT_SIMILARITY_THRESHOLD,
) -> bool:
    """True when two lessons are equivalent enough to store as one item."""
    a = normalize_lesson_text(left)
    b = normalize_lesson_text(right)
    if not a or not b:
        return False
    if a == b:
        return True
    shorter, longer = sorted((a, b), key=len)
    if len(shorter) >= 24 and shorter in longer:
        return True
    if len(shorter) < _MIN_FUZZY_MATCH_CHARS:
        return False
    return SequenceMatcher(None, a, b).ratio() >= threshold


def _seen_count(line: str) -> int:
    match = _SEEN_SUFFIX_RE.search(line or '')
    if not match:
        return 1
    try:
        return max(1, int(match.group(1)))
    except ValueError:
        return 1


def _with_seen_count(line: str, count: int) -> str:
    base = _SEEN_SUFFIX_RE.sub('', line or '').rstrip()
    return f'{base} (seen {count}x)'


def append_deduped_note_entry(
    existing: str,
    value: str,
    *,
    max_entries: int = 50,
    timestamp: str | None = None,
    threshold: float = _DEFAULT_SIMILARITY_THRESHOLD,
) -> tuple[str, bool]:
    """Append a timestamped scratchpad entry, merging near-duplicates."""
    v = (value or '').strip()
    if not v:
        return existing, False

    stamp = timestamp or time.strftime('%Y-%m-%d %H:%M', time.gmtime())
    lines = [line for line in (existing or '').splitlines() if line.strip()]
    for idx, line in enumerate(lines):
        if lessons_are_similar(line, v, threshold=threshold):
            lines[idx] = _with_seen_count(line, _seen_count(line) + 1)
            return '\n'.join(lines[-max_entries:]), False

    lines.append(f'- [{stamp}] {v}')
    return '\n'.join(lines[-max_entries:]), True


def _markdown_bodies(markdown: str) -> list[str]:
    matches = list(_MD_HEADING_RE.finditer(markdown or ''))
    if not matches:
        return [markdown] if markdown.strip() else []
    bodies: list[str] = []
    for idx, match in enumerate(matches):
        start = match.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(markdown)
        bodies.append(markdown[start:end].strip())
    return bodies


def append_markdown_lesson(
    path: Path,
    lesson: str,
    *,
    summary: str,
    timestamp: str | None = None,
    threshold: float = _DEFAULT_SIMILARITY_THRESHOLD,
) -> bool:
    """Append a lesson markdown section unless an equivalent one exists.

    Returns True when a new section was written, False when the lesson was
    empty or deduplicated.
    """
    v = (lesson or '').strip()
    if not v:
        return False

    existing = ''
    if path.exists():
        try:
            existing = path.read_text(encoding='utf-8')
        except OSError:
            existing = ''

    for body in _markdown_bodies(existing):
        if lessons_are_similar(body, v, threshold=threshold):
            return False

    stamp = timestamp or time.strftime('%Y-%m-%d %H:%M', time.localtime())
    safe_summary = re.sub(r'\s+', ' ', (summary or 'Task').strip())[:100] or 'Task'
    entry = f'\n## {stamp} - {safe_summary}\n{v}\n'
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'a', encoding='utf-8') as f:
        f.write(entry)
    return True


__all__ = [
    'append_deduped_note_entry',
    'append_markdown_lesson',
    'lessons_are_similar',
    'normalize_lesson_text',
]
