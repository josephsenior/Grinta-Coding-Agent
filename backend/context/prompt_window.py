"""Token-budget-aware event windowing before prompt rendering."""

from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

_EVENT_TOKEN_CACHE: dict[str, int] = {}
_EVENT_TOKEN_CACHE_MAX = 4096

from backend.inference.provider_capabilities import model_token_correction
from backend.ledger.action import Action
from backend.ledger.event import Event
from backend.ledger.observation.agent import AgentCondensationObservation
from backend.ledger.serialization.event import event_to_dict

_DEFAULT_BUDGET_RATIO = 0.50
_DEFAULT_MIN_EVENTS = 150
_DEFAULT_MAX_EVENTS = 240


@dataclass(frozen=True)
class PromptWindowResult:
    """Result of selecting the bounded prompt event view."""

    events: list[Event]
    original_events: int
    selected_events: int
    dropped_events: int
    estimated_tokens: int
    selected_estimated_tokens: int
    token_budget: int | None
    protected_events: int
    windowed: bool
    reason: str
    cache_fingerprint: str


def select_prompt_events(
    events: Iterable[Event],
    llm_config: object,
) -> PromptWindowResult:
    """Return a token-budget-aware prompt view preserving recent causal chunks."""
    event_list = list(events)
    full_tokens = estimate_events_tokens(event_list)
    budget = _history_token_budget(llm_config)
    max_events = _positive_int_attr(
        llm_config, 'prompt_history_max_events', _DEFAULT_MAX_EVENTS
    )
    min_events = _positive_int_attr(
        llm_config, 'prompt_history_min_events', _DEFAULT_MIN_EVENTS
    )
    enabled = _bool_attr(llm_config, 'prompt_history_windowing_enabled', True)

    over_budget = budget is not None and full_tokens > budget
    over_count = max_events is not None and len(event_list) > max_events
    should_window = enabled and (over_budget or over_count) and (
        len(event_list) >= min_events or over_budget
    )
    if not should_window:
        return _result(
            events=event_list,
            original_events=len(event_list),
            estimated_tokens=full_tokens,
            selected_estimated_tokens=full_tokens,
            token_budget=budget,
            protected_events=0,
            windowed=False,
            reason='within_budget',
        )

    protected = _protected_summary_events(event_list)
    protected_ids = {id(event) for event in protected}
    chunks = _causal_chunks(
        event for event in event_list if id(event) not in protected_ids
    )
    protected_tokens = estimate_events_tokens(protected)
    selected_chunks: list[list[Event]] = []
    selected_tokens = protected_tokens
    selected_count = len(protected)
    reason_parts: list[str] = []
    if over_budget:
        reason_parts.append('token_budget')
    if over_count:
        reason_parts.append('event_count')

    for chunk in reversed(chunks):
        chunk_tokens = estimate_events_tokens(chunk)
        chunk_count = len(chunk)
        has_tail = bool(selected_chunks)
        count_allows = max_events is None or selected_count + chunk_count <= max_events
        budget_allows = budget is None or selected_tokens + chunk_tokens <= budget
        must_keep_latest = not has_tail
        if not must_keep_latest and (not count_allows or not budget_allows):
            continue
        if must_keep_latest and not budget_allows and budget is not None:
            remaining = max(1, budget - selected_tokens)
            chunk = _truncate_chunk_to_budget(chunk, remaining)
            chunk_tokens = estimate_events_tokens(chunk)
            chunk_count = len(chunk)
        selected_chunks.append(chunk)
        selected_tokens += chunk_tokens
        selected_count += chunk_count

    selected_chunks.reverse()
    selected = protected + [event for chunk in selected_chunks for event in chunk]
    if budget is not None:
        selected = _enforce_token_ceiling(selected, budget, protected)
    return _result(
        events=selected,
        original_events=len(event_list),
        estimated_tokens=full_tokens,
        selected_estimated_tokens=estimate_events_tokens(selected),
        token_budget=budget,
        protected_events=len(protected),
        windowed=True,
        reason='+'.join(reason_parts) or 'windowed',
    )


def estimate_event_tokens(event: Event) -> int:
    """Best-effort token estimate for a single event (cached by fingerprint)."""
    fp = event_fingerprint(event)
    cached = _EVENT_TOKEN_CACHE.get(fp)
    if cached is not None:
        return cached
    text = _event_payload_text(event)
    if not text:
        tokens = 0
    else:
        tokenizer = _tokenizer()
        if tokenizer is not None:
            try:
                tokens = max(1, len(tokenizer.encode(text)))
            except Exception:
                tokens = max(1, len(text) // 4)
        else:
            tokens = max(1, len(text) // 4)
    if len(_EVENT_TOKEN_CACHE) >= _EVENT_TOKEN_CACHE_MAX:
        _EVENT_TOKEN_CACHE.clear()
    _EVENT_TOKEN_CACHE[fp] = tokens
    return tokens


def estimate_events_tokens(events: Iterable[Event]) -> int:
    """Best-effort token estimate for event payloads."""
    total = 0
    for event in events:
        total += estimate_event_tokens(event)
    if total > 0:
        return total
    text = '\n'.join(_event_payload_text(event) for event in events)
    if not text:
        return 0
    tokenizer = _tokenizer()
    if tokenizer is not None:
        try:
            return max(1, len(tokenizer.encode(text)))
        except Exception:
            pass
    return max(1, len(text) // 4)


def event_fingerprint(event: Event) -> str:
    """Stable fingerprint for prompt-window/cache diagnostics."""
    payload = _event_payload_text(event)
    digest = hashlib.sha1(payload.encode('utf-8', 'ignore')).hexdigest()[:16]
    event_id = getattr(event, 'id', None)
    return f'{type(event).__name__}:{event_id}:{digest}'


def _history_token_budget(llm_config: object) -> int | None:
    explicit = _positive_int_attr(llm_config, 'prompt_history_token_budget', None)
    if explicit is not None:
        return explicit
    max_input = _positive_int_attr(llm_config, 'max_input_tokens', None)
    if max_input is None:
        return None
    ratio = _float_attr(llm_config, 'prompt_history_budget_ratio', _DEFAULT_BUDGET_RATIO)
    ratio = max(0.05, min(0.95, ratio))
    model = str(getattr(llm_config, 'model', '') or '')
    factor, _ = model_token_correction(model)
    return max(1, int((max_input * ratio) / factor))


def _protected_summary_events(events: list[Event]) -> list[Event]:
    protected: list[Event] = []
    for event in events:
        if not isinstance(event, AgentCondensationObservation):
            continue
        content = (getattr(event, 'content', '') or '').strip()
        if not content or content == '<MASKED>':
            continue
        protected.append(event)
    return protected


def _enforce_token_ceiling(
    selected: list[Event],
    budget: int,
    protected: list[Event],
) -> list[Event]:
    """Drop oldest removable causal units until the selection fits the token budget."""
    if estimate_events_tokens(selected) <= budget:
        return selected
    protected_ids = {id(event) for event in protected}
    removable = [event for event in selected if id(event) not in protected_ids]
    protected_events = [event for event in selected if id(event) in protected_ids]
    protected_tokens = estimate_events_tokens(protected_events)
    chunks = _causal_chunks(removable)
    kept_chunks: list[list[Event]] = []
    kept_tokens = protected_tokens
    for chunk in reversed(chunks):
        chunk_tokens = estimate_events_tokens(chunk)
        if not kept_chunks:
            if kept_tokens + chunk_tokens > budget:
                chunk = _truncate_chunk_to_budget(
                    chunk, max(1, budget - kept_tokens)
                )
                chunk_tokens = estimate_events_tokens(chunk)
            kept_chunks.append(chunk)
            kept_tokens += chunk_tokens
            continue
        if kept_tokens + chunk_tokens <= budget:
            kept_chunks.append(chunk)
            kept_tokens += chunk_tokens
    kept_chunks.reverse()
    result = protected_events + [event for chunk in kept_chunks for event in chunk]
    while estimate_events_tokens(result) > budget:
        tail = [event for event in result if id(event) not in protected_ids]
        if not tail:
            break
        remaining = max(1, budget - protected_tokens)
        truncated_tail = _truncate_chunk_to_budget(tail, remaining)
        result = protected_events + truncated_tail
        if estimate_events_tokens(result) <= budget:
            break
        if not _drop_oldest_removable_unit(tail):
            break
        result = protected_events + tail
    return result


def _causal_chunks(events: Iterable[Event]) -> list[list[Event]]:
    chunks: list[list[Event]] = []
    current: list[Event] = []
    for event in events:
        if isinstance(event, Action) and current:
            chunks.append(current)
            current = [event]
        else:
            current.append(event)
    if current:
        chunks.append(current)
    return chunks


def _copy_event_for_prompt(event: Event) -> Event:
    """Return a prompt-only copy so windowing never mutates state.history."""
    try:
        return event_from_dict(event_to_dict(event))
    except Exception:
        return copy.deepcopy(event)


def _drop_oldest_removable_unit(chunk: list[Event]) -> bool:
    """Drop the oldest causal unit without splitting an action from its results."""
    if len(chunk) <= 1:
        return False
    first_action_idx = next(
        (i for i, event in enumerate(chunk) if isinstance(event, Action)),
        len(chunk),
    )
    if first_action_idx > 0:
        chunk.pop(0)
        return True
    if isinstance(chunk[0], Action):
        chunk.pop(0)
        while chunk and not isinstance(chunk[0], Action):
            chunk.pop(0)
        return True
    return False


def _truncate_chunk_to_budget(chunk: list[Event], token_budget: int) -> list[Event]:
    """Truncate events in *chunk* so their estimated tokens fit within *token_budget*.

    The largest observation events are truncated first (by replacing their
    ``content`` field with a head/tail excerpt).  Action events are never
    truncated — they carry the tool-call structure the LLM needs.  If
    truncation of observations is insufficient, the oldest non-action events
    are dropped entirely.
    """
    if not chunk or token_budget <= 0:
        return chunk

    original = list(chunk)
    chunk = [_copy_event_for_prompt(event) for event in chunk]

    _TRUNCATION_MARKER = '\n\n[... truncated to fit context window ...]\n\n'
    _HEAD_CHARS = 500
    _TAIL_CHARS = 500

    current_tokens = estimate_events_tokens(chunk)
    if current_tokens <= token_budget:
        return chunk

    sized = []
    for i, event in enumerate(chunk):
        if isinstance(event, Action):
            continue
        content = getattr(event, 'content', None)
        if not isinstance(content, str) or len(content) < _HEAD_CHARS + _TAIL_CHARS:
            continue
        sized.append((len(content), i, event))

    sized.sort(reverse=True)

    for _size, idx, event in sized:
        if estimate_events_tokens(chunk) <= token_budget:
            break
        content = getattr(event, 'content', '')
        truncated = content[:_HEAD_CHARS] + _TRUNCATION_MARKER + content[-_TAIL_CHARS:]
        try:
            event.content = truncated
        except Exception:
            pass

    if estimate_events_tokens(chunk) <= token_budget:
        return chunk

    while len(chunk) > 1 and estimate_events_tokens(chunk) > token_budget:
        if not _drop_oldest_removable_unit(chunk):
            break

    if not chunk and original:
        for event in reversed(original):
            if isinstance(event, Action):
                return [_copy_event_for_prompt(event)]
        return [_copy_event_for_prompt(original[-1])]

    return chunk


def _event_payload_text(event: Event) -> str:
    try:
        return json.dumps(event_to_dict(event), default=str, sort_keys=True)
    except Exception:
        return str(getattr(event, 'message', '') or getattr(event, 'content', '') or event)


def _result(
    *,
    events: list[Event],
    original_events: int,
    estimated_tokens: int,
    selected_estimated_tokens: int,
    token_budget: int | None,
    protected_events: int,
    windowed: bool,
    reason: str,
) -> PromptWindowResult:
    fingerprint_payload = '|'.join(event_fingerprint(event) for event in events)
    cache_fingerprint = hashlib.sha1(
        fingerprint_payload.encode('utf-8', 'ignore')
    ).hexdigest()[:16]
    return PromptWindowResult(
        events=events,
        original_events=original_events,
        selected_events=len(events),
        dropped_events=max(0, original_events - len(events)),
        estimated_tokens=estimated_tokens,
        selected_estimated_tokens=selected_estimated_tokens,
        token_budget=token_budget,
        protected_events=protected_events,
        windowed=windowed,
        reason=reason,
        cache_fingerprint=cache_fingerprint,
    )


def _positive_int_attr(obj: object, name: str, default: int | None) -> int | None:
    value = getattr(obj, name, default)
    if isinstance(value, bool):
        return default
    if isinstance(value, int) and value > 0:
        return value
    if isinstance(value, str):
        try:
            parsed = int(value)
        except ValueError:
            return default
        return parsed if parsed > 0 else default
    return default


def _float_attr(obj: object, name: str, default: float) -> float:
    value = getattr(obj, name, default)
    if isinstance(value, bool):
        return default
    if isinstance(value, (float, int)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return default
    return default


def _bool_attr(obj: object, name: str, default: bool) -> bool:
    value = getattr(obj, name, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() not in {'0', 'false', 'no', 'off'}
    return default


@lru_cache(maxsize=1)
def _tokenizer() -> Any | None:
    try:
        import tiktoken  # type: ignore

        return tiktoken.get_encoding('cl100k_base')
    except Exception:
        return None


__all__ = [
    'PromptWindowResult',
    'estimate_event_tokens',
    'estimate_events_tokens',
    'event_fingerprint',
    'select_prompt_events',
]
