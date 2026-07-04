"""Resolve acceptance-criteria evidence references to verbatim tool output."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from backend.core.constants import PERSISTED_OUTPUT_TAG
from backend.ledger.event import Event
from backend.ledger.observation import Observation

_LINE_SLICE_RE = re.compile(
    r'^(.+?):lines\[(\d+)(?:-(\d+))?\]$',
    re.IGNORECASE,
)
_EVENT_REF_RE = re.compile(r'^event:(\d+)$', re.IGNORECASE)


class EvidenceRefError(ValueError):
    """Raised when an evidence reference cannot be resolved."""


@dataclass(frozen=True)
class ParsedEvidenceRef:
    """Parsed evidence reference."""

    lookup_key: str
    event_id: int | None
    line_start: int | None
    line_end: int | None


def parse_evidence_ref(ref: str) -> ParsedEvidenceRef:
    """Parse ``tool_call_id``, ``event:<id>``, or either with ``:lines[start-end]``."""
    raw = str(ref or '').strip()
    if not raw:
        raise EvidenceRefError('evidence_ref must be a non-empty string')

    line_start: int | None = None
    line_end: int | None = None
    base = raw

    slice_match = _LINE_SLICE_RE.match(raw)
    if slice_match:
        base = slice_match.group(1).strip()
        line_start = int(slice_match.group(2))
        if slice_match.group(3) is not None:
            line_end = int(slice_match.group(3))
        elif line_start is not None:
            line_end = line_start

    event_match = _EVENT_REF_RE.match(base)
    if event_match:
        return ParsedEvidenceRef(
            lookup_key=base,
            event_id=int(event_match.group(1)),
            line_start=line_start,
            line_end=line_end,
        )

    return ParsedEvidenceRef(
        lookup_key=base,
        event_id=None,
        line_start=line_start,
        line_end=line_end,
    )


def apply_line_slice(content: str, start: int | None, end: int | None) -> str:
    """Return a 1-based inclusive line slice from *content*."""
    if start is None:
        return content
    lines = content.splitlines()
    if not lines:
        return content
    slice_start = max(1, start)
    slice_end = end if end is not None else slice_start
    slice_end = min(len(lines), max(slice_start, slice_end))
    return '\n'.join(lines[slice_start - 1 : slice_end])


def _tool_call_id_from_event(event: Event) -> str | None:
    meta = getattr(event, 'tool_call_metadata', None)
    if meta is None:
        return None
    tool_call_id = getattr(meta, 'tool_call_id', None)
    if tool_call_id:
        return str(tool_call_id)
    return None


def _observation_content(event: Event) -> str:
    content = str(getattr(event, 'content', '') or '')
    if PERSISTED_OUTPUT_TAG not in content:
        return content

    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith('Full output saved to:'):
            path_text = stripped.split(':', 1)[1].strip()
            path = Path(path_text)
            if path.is_file():
                try:
                    return path.read_text(encoding='utf-8')
                except OSError:
                    break
    return content


def _lookup_content(parsed: ParsedEvidenceRef, events: Iterable[Event]) -> str | None:
    if parsed.event_id is not None:
        for event in events:
            if getattr(event, 'id', None) == parsed.event_id:
                if isinstance(event, Observation):
                    return _observation_content(event)
                content = str(getattr(event, 'content', '') or '')
                return content or None
        return None

    lookup = parsed.lookup_key
    for event in events:
        if _tool_call_id_from_event(event) != lookup:
            continue
        if isinstance(event, Observation):
            return _observation_content(event)
        content = str(getattr(event, 'content', '') or '')
        if content:
            return content

    # Some streams attach metadata only on the paired observation; scan observations.
    for event in events:
        if not isinstance(event, Observation):
            continue
        if _tool_call_id_from_event(event) == lookup:
            return _observation_content(event)
    return None


def resolve_evidence_ref(ref: str, events: Iterable[Event]) -> str:
    """Resolve *ref* to verbatim output text from session *events*."""
    parsed = parse_evidence_ref(ref)
    content = _lookup_content(parsed, events)
    if not content:
        raise EvidenceRefError(
            f'Could not resolve evidence_ref {ref!r}: no matching tool output in session'
        )
    return apply_line_slice(content, parsed.line_start, parsed.line_end)


def collect_session_events(event_stream: Any) -> list[Event]:
    """Load events from an event stream for evidence resolution."""
    if event_stream is None:
        return []
    search = getattr(event_stream, 'search_events', None)
    if not callable(search):
        return []
    try:
        return list(search())
    except TypeError:
        try:
            return list(search(start_id=0))
        except Exception:
            return []
    except Exception:
        return []


__all__ = [
    'EvidenceRefError',
    'ParsedEvidenceRef',
    'apply_line_slice',
    'collect_session_events',
    'parse_evidence_ref',
    'resolve_evidence_ref',
]
