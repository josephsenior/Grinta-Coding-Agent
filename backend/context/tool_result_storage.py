"""Persist oversized tool outputs to disk and apply per-message budgets.

Inspired by Claude Code's tool-result budget layer: shed observation bulk
before conversation summarization so pytest logs and file reads do not
dominate the prompt window.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from backend.core.constants import (
    DEFAULT_TOOL_RESULT_PERSIST_THRESHOLD_CHARS,
    DEFAULT_TOOL_RESULT_PREVIEW_CHARS,
    DEFAULT_TOOL_RESULTS_PER_MESSAGE_CHARS,
)
from backend.core.logger import app_logger as logger
from backend.ledger.event import Event
from backend.ledger.observation import Observation
from backend.ledger.observation.commands import CmdOutputObservation
from backend.ledger.observation.files import FileReadObservation
from backend.ledger.observation.terminal import TerminalObservation
from backend.ledger.serialization.event import event_from_dict, event_to_dict

PERSISTED_OUTPUT_TAG = '<persisted-output>'
TOOL_RESULT_CLEARED_MESSAGE = '[Old tool result content cleared]'
TOOL_RESULT_REPLACEMENTS_KEY = 'tool_result_replacements'

_PYTEST_SUMMARY_RE = re.compile(
    r'=+\s*(\d+\s+(?:failed|passed|error)[^\n=]+)\s*=+',
    re.IGNORECASE,
)


def _tool_results_dir() -> Path:
    from backend.core.workspace_resolution import workspace_agent_state_dir

    path = workspace_agent_state_dir() / 'tool-results'
    path.mkdir(parents=True, exist_ok=True)
    return path


def _stable_filename(event: Event, content: str) -> str:
    event_id = getattr(event, 'id', None)
    if isinstance(event_id, int):
        return f'event_{event_id}.txt'
    digest = hashlib.sha1(
        content[:4000].encode('utf-8', 'ignore'), usedforsecurity=False
    ).hexdigest()[:12]
    return f'hash_{digest}.txt'


def persist_tool_output(content: str, event: Event) -> tuple[str, str]:
    """Write *content* to disk and return ``(filepath, preview)``."""
    filepath = _tool_results_dir() / _stable_filename(event, content)
    filepath.write_text(content, encoding='utf-8')
    preview_limit = DEFAULT_TOOL_RESULT_PREVIEW_CHARS
    if len(content) <= preview_limit:
        preview = content
        has_more = False
    else:
        head = content[: preview_limit // 2]
        tail = content[-(preview_limit // 2) :]
        preview = (
            f'{head}\n\n[... {len(content):,} chars persisted to disk ...]\n\n{tail}'
        )
        has_more = True
    block = (
        f'{PERSISTED_OUTPUT_TAG}\n'
        f'Full output saved to: {filepath}\n'
        f'Original size: {len(content):,} characters\n'
        f'{"Has more content on disk." if has_more else ""}\n'
        f'Preview:\n{preview}\n'
        f'{PERSISTED_OUTPUT_TAG}'
    )
    return str(filepath), block.strip()


def _copy_event_with_content(event: Event, content: str) -> Event:
    copied = event_from_dict(event_to_dict(event))
    try:
        setattr(copied, 'content', content)
    except Exception:
        pass
    return copied


def _should_persist_observation(event: Event, content: str, threshold: int) -> bool:
    if len(content) < threshold:
        return False
    if isinstance(
        event, (CmdOutputObservation, FileReadObservation, TerminalObservation)
    ):
        return True
    if isinstance(event, Observation) and type(event).__name__ == 'MCPObservation':
        return True
    return False


def _shrink_observation_batch(
    result: list[Event],
    batch: list[tuple[int, Event, str]],
    *,
    persist_threshold: int,
    per_message_chars: int,
) -> None:
    """Persist or trim observations in *batch* until under budget."""
    if not batch:
        return
    total = sum(len(content) for _, _, content in batch)
    if total <= per_message_chars:
        for idx, event, content in batch:
            result[idx] = _copy_event_with_content(event, content)
        return

    remaining = list(batch)
    for _, event, content in sorted(
        remaining, key=lambda item: len(item[2]), reverse=True
    ):
        if sum(len(c) for _, _, c in remaining) <= per_message_chars:
            break
        replacement = content
        if _should_persist_observation(event, content, persist_threshold // 2):
            try:
                _, replacement = persist_tool_output(content, event)
            except OSError:
                logger.debug('Tool result persistence failed', exc_info=True)
                replacement = (
                    content[:2000] + '\n[... output truncated ...]\n' + content[-1000:]
                )
        remaining = [
            (idx, ev, replacement if ev is event else cont)
            for idx, ev, cont in remaining
        ]
    for idx, event, content in remaining:
        result[idx] = _copy_event_with_content(event, content)


def _get_replacement_map(state: object | None) -> dict[str, str]:
    if state is None:
        return {}
    extra = getattr(state, 'extra_data', None)
    if not isinstance(extra, dict):
        return {}
    raw = extra.get(TOOL_RESULT_REPLACEMENTS_KEY)
    return dict(raw) if isinstance(raw, dict) else {}


def _set_replacement_map(state: object, replacements: dict[str, str]) -> None:
    state.set_extra(  # type: ignore[attr-defined]
        TOOL_RESULT_REPLACEMENTS_KEY,
        replacements,
        source='tool_result_storage',
    )


def persist_tool_result_on_observation(event: Event, state: object | None) -> None:
    """Persist oversized tool output at observation emit time with frozen preview."""
    if state is None or not isinstance(event, Observation):
        return
    content = str(getattr(event, 'content', '') or '')
    if not content:
        return
    event_id = getattr(event, 'id', None)
    if not isinstance(event_id, int):
        return
    if not _should_persist_observation(
        event, content, DEFAULT_TOOL_RESULT_PERSIST_THRESHOLD_CHARS
    ):
        return
    replacements = _get_replacement_map(state)
    key = str(event_id)
    if key in replacements:
        return
    try:
        _, preview = persist_tool_output(content, event)
        replacements[key] = preview
        _set_replacement_map(state, replacements)
        logger.debug('Frozen tool result replacement for event id=%d', event_id)
    except OSError:
        logger.debug('Tool result persistence at emit failed', exc_info=True)


def apply_frozen_tool_replacements(
    events: list[Event],
    state: object | None,
) -> list[Event]:
    """Re-apply cached tool-result previews keyed by event id."""
    replacements = _get_replacement_map(state)
    if not replacements:
        return events
    result: list[Event] = []
    for event in events:
        event_id = getattr(event, 'id', None)
        if isinstance(event_id, int) and str(event_id) in replacements:
            result.append(_copy_event_with_content(event, replacements[str(event_id)]))
            continue
        result.append(event)
    return result


def apply_tool_result_budget(
    events: list[Event],
    *,
    persist_threshold: int = DEFAULT_TOOL_RESULT_PERSIST_THRESHOLD_CHARS,
    per_message_chars: int = DEFAULT_TOOL_RESULTS_PER_MESSAGE_CHARS,
) -> list[Event]:
    """Return prompt-only copies with oversized observations persisted or trimmed."""
    if not events:
        return events

    result: list[Event] = []
    batch: list[tuple[int, Event, str]] = []

    def flush_batch() -> None:
        _shrink_observation_batch(
            result,
            batch,
            persist_threshold=persist_threshold,
            per_message_chars=per_message_chars,
        )
        batch.clear()

    for event in events:
        if isinstance(event, Observation):
            content = str(getattr(event, 'content', '') or '')
            if not content:
                result.append(event)
                flush_batch()
                continue
            if _should_persist_observation(event, content, persist_threshold):
                try:
                    _, preview = persist_tool_output(content, event)
                    result.append(_copy_event_with_content(event, preview))
                    flush_batch()
                    continue
                except OSError:
                    logger.debug('Tool result persistence failed', exc_info=True)
            idx = len(result)
            result.append(event)
            batch.append((idx, event, content))
            if sum(len(item[2]) for item in batch) > per_message_chars:
                flush_batch()
            continue

        flush_batch()
        result.append(event)

    flush_batch()
    return result


def extract_latest_pytest_summary(events: list[Event]) -> str | None:
    """Return the most recent pytest summary line from command observations."""
    latest: str | None = None
    for event in reversed(events):
        if not isinstance(event, CmdOutputObservation):
            continue
        content = str(getattr(event, 'content', '') or '')
        match = _PYTEST_SUMMARY_RE.search(content)
        if match:
            latest = match.group(1).strip()
            break
    return latest


__all__ = [
    'PERSISTED_OUTPUT_TAG',
    'TOOL_RESULT_CLEARED_MESSAGE',
    'TOOL_RESULT_REPLACEMENTS_KEY',
    'apply_frozen_tool_replacements',
    'apply_tool_result_budget',
    'extract_latest_pytest_summary',
    'persist_tool_output',
    'persist_tool_result_on_observation',
]
