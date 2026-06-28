"""Token-budget-aware event windowing before prompt rendering."""

from __future__ import annotations

import copy
import hashlib
import json
import threading
from collections import OrderedDict
from collections.abc import Iterable
from contextvars import ContextVar
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from backend.core.constants import (
    DEFAULT_EMERGENCY_PROMPT_MIN_EVENTS,
    DEFAULT_PROMPT_MIN_TAIL_TOKENS,
    DEFAULT_PROMPT_MIN_TOOL_LOOPS,
)
from backend.inference.capabilities.context_limits import limits_from_config
from backend.inference.capabilities.provider_capabilities import (
    model_is_small,
    model_token_correction,
)
from backend.ledger.action import Action
from backend.ledger.action.message import MessageAction
from backend.ledger.event import Event, EventSource
from backend.ledger.observation.agent import AgentCondensationObservation
from backend.ledger.serialization.event import event_from_dict, event_to_dict

_DEFAULT_MIN_EVENTS = 150
_DEFAULT_MAX_EVENTS = 240
_MASKED_PLACEHOLDER = '<MASKED>'
_EVENT_TOKEN_CACHE: OrderedDict[str, int] = OrderedDict()
_EVENT_TOKEN_CACHE_MAX = 4096
_EVENT_TOKEN_CACHE_LOCK = threading.Lock()
_CURRENT_MODEL: ContextVar[str | None] = ContextVar(
    'grinta_current_tokenizer_model', default=None
)


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


@dataclass
class _WindowingContext:
    event_list: list[Event]
    original_event_count: int
    full_tokens: int
    budget: int | None
    max_events: int | None
    min_events: int
    enabled: bool
    over_budget: bool
    over_count: bool
    should_window: bool
    reason_parts: list[str]


def _check_should_window(enabled, over_budget, over_count, event_list, min_events):
    if not enabled:
        return False
    if not (over_budget or over_count):
        return False
    return len(event_list) >= min_events or over_budget


def _build_reason_parts(over_budget, over_count):
    parts = []
    if over_budget:
        parts.append('token_budget')
    if over_count:
        parts.append('event_count')
    return parts


def _build_windowing_context(
    events: list[Event],
    llm_config: object,
    *,
    state: object | None = None,
    emergency_only: bool = False,
    tool_budget_applied: bool = False,
) -> _WindowingContext:
    from backend.context.tool_result_storage import apply_tool_result_budget

    event_list = events if tool_budget_applied else apply_tool_result_budget(events)
    original_event_count = len(event_list)
    full_tokens = estimate_prompt_events_tokens(event_list)
    budget = _history_token_budget(llm_config, state=state)
    max_events = _prompt_history_max_events(llm_config)
    default_min_events = (
        DEFAULT_EMERGENCY_PROMPT_MIN_EVENTS if emergency_only else _DEFAULT_MIN_EVENTS
    )
    min_events = _positive_int_attr(
        llm_config, 'prompt_history_min_events', default_min_events
    )
    enabled = _bool_attr(llm_config, 'prompt_history_windowing_enabled', True)

    over_budget = budget is not None and full_tokens > budget
    over_count = max_events is not None and len(event_list) > max_events
    if emergency_only:
        over_count = False
    should_window = _check_should_window(
        enabled, over_budget, over_count, event_list, min_events
    )
    reason_parts = _build_reason_parts(over_budget, over_count)
    if emergency_only and should_window:
        reason_parts.append('emergency_only')

    return _WindowingContext(
        event_list=event_list,
        original_event_count=original_event_count,
        full_tokens=full_tokens,
        budget=budget,
        max_events=max_events,
        min_events=min_events if min_events is not None else default_min_events,
        enabled=enabled,
        over_budget=over_budget,
        over_count=over_count,
        should_window=should_window,
        reason_parts=reason_parts,
    )


def _inject_working_set(ctx: _WindowingContext, raw_events: list[Event]) -> None:
    from backend.context.memory.working_set import build_working_set_observation

    if any(getattr(event, 'is_working_set', False) for event in ctx.event_list):
        return

    working_set = build_working_set_observation(raw_events)
    if working_set is not None:
        ctx.event_list = [working_set, *ctx.event_list]
        ctx.full_tokens = estimate_prompt_events_tokens(ctx.event_list)
        ctx.over_budget = ctx.budget is not None and ctx.full_tokens > ctx.budget
        ctx.over_count = (
            ctx.max_events is not None and len(ctx.event_list) > ctx.max_events
        )


def _event_id_set(events):
    return {id(event) for event in events}


def _non_protected_chunks(all_events, protected_ids):
    return _causal_chunks(
        event for event in all_events if id(event) not in protected_ids
    )


def _chunk_fits(chunk_count, chunk_tokens, ctx, selected_count, selected_tokens):
    count_ok = ctx.max_events is None or selected_count + chunk_count <= ctx.max_events
    budget_ok = ctx.budget is None or selected_tokens + chunk_tokens <= ctx.budget
    return count_ok and budget_ok


def _truncate_if_over_budget(chunk, chunk_tokens, ctx, selected_tokens):
    budget_allows = ctx.budget is None or selected_tokens + chunk_tokens <= ctx.budget
    if budget_allows:
        return chunk, chunk_tokens, len(chunk)
    remaining = max(1, ctx.budget - selected_tokens)
    chunk = _truncate_chunk_to_budget(chunk, remaining)
    return chunk, estimate_prompt_events_tokens(chunk), len(chunk)


def _resolve_chunk(chunk, ctx, selected_chunks, selected_tokens, selected_count):
    chunk_tokens = estimate_prompt_events_tokens(chunk)
    chunk_count = len(chunk)
    must_keep_latest = not bool(selected_chunks)
    if not must_keep_latest and not _chunk_fits(
        chunk_count, chunk_tokens, ctx, selected_count, selected_tokens
    ):
        return None, 0, 0
    if must_keep_latest:
        chunk, chunk_tokens, chunk_count = _truncate_if_over_budget(
            chunk, chunk_tokens, ctx, selected_tokens
        )
    return chunk, chunk_tokens, chunk_count


def _select_causal_chunks(
    ctx: _WindowingContext,
    protected: list[Event],
) -> tuple[list[list[Event]], int, int]:
    protected_ids = _event_id_set(protected)
    chunks = _non_protected_chunks(ctx.event_list, protected_ids)
    protected_tokens = estimate_prompt_events_tokens(protected)
    selected_chunks: list[list[Event]] = []
    selected_tokens = protected_tokens
    selected_count = len(protected)

    for chunk in reversed(chunks):
        chunk, chunk_tokens, chunk_count = _resolve_chunk(
            chunk, ctx, selected_chunks, selected_tokens, selected_count
        )
        if chunk is None:
            continue
        selected_chunks.append(chunk)
        selected_tokens += chunk_tokens
        selected_count += chunk_count

    selected_chunks.reverse()
    return selected_chunks, selected_tokens, selected_count


def _apply_windowing_constraints(
    selected: list[Event],
    ctx: _WindowingContext,
    all_events: list[Event],
    protected: list[Event],
    llm_config: object,
) -> list[Event]:
    min_tool_loops = _non_negative_int_attr(
        llm_config,
        'prompt_history_min_tool_loops',
        DEFAULT_PROMPT_MIN_TOOL_LOOPS,
    )
    if min_tool_loops > 0:
        selected = _enforce_min_tool_loops(
            selected,
            all_events,
            protected,
            min_tool_loops=min_tool_loops,
        )
    if ctx.budget is not None:
        min_tail_tokens = _non_negative_int_attr(
            llm_config,
            'prompt_history_min_tail_tokens',
            DEFAULT_PROMPT_MIN_TAIL_TOKENS,
        )
        if min_tail_tokens > 0:
            selected = _enforce_min_tail_tokens(
                selected,
                all_events,
                protected,
                budget=ctx.budget,
                min_tail_tokens=min_tail_tokens,
            )
        selected = _enforce_token_ceiling(selected, ctx.budget, protected)
    if ctx.max_events is not None:
        selected = _enforce_max_event_count(
            selected,
            protected,
            all_events,
            max_events=ctx.max_events,
            min_tool_loops=min_tool_loops,
        )
    return selected


def _enforce_max_event_count(
    selected: list[Event],
    protected: list[Event],
    all_events: list[Event],
    *,
    max_events: int,
    min_tool_loops: int = 0,
) -> list[Event]:
    """Drop oldest removable events until the selection fits *max_events*.

    Events are dropped at causal-chunk granularity to preserve
    ``(action, observation)`` pair integrity. Dropping one half of a pair
    produces an invalid message sequence that most LLM APIs reject.
    """
    if len(selected) <= max_events:
        return selected
    protected_ids = _event_id_set(protected)
    required_ids: set[int] = set()
    if min_tool_loops > 0:
        chunks = _non_protected_chunks(all_events, protected_ids)
        if len(chunks) >= min_tool_loops:
            required_ids = _required_tail_ids(chunks, min_tool_loops)
    keep_ids = protected_ids | required_ids
    protected_events = [event for event in selected if id(event) in keep_ids]
    removable = [event for event in selected if id(event) not in keep_ids]
    if len(protected_events) >= max_events:
        return selected
    slots = max_events - len(protected_events)
    # Drop at causal-chunk granularity to preserve tool_call/tool_result pairs.
    removable_chunks = _causal_chunks(removable)
    kept_chunks: list[list[Event]] = []
    total = 0
    for chunk in reversed(removable_chunks):
        if total + len(chunk) > slots:
            break
        kept_chunks.insert(0, chunk)
        total += len(chunk)
    kept_removable = [e for chunk in kept_chunks for e in chunk]
    return _dedupe_events_preserve_order(protected_events + kept_removable)


def _build_windowed_result(ctx, protected, selected_chunks, llm_config):
    selected = protected + _flatten_chunks(selected_chunks)
    selected = _apply_windowing_constraints(
        selected, ctx, ctx.event_list, protected, llm_config
    )
    return _result(
        events=selected,
        original_events=ctx.original_event_count,
        estimated_tokens=ctx.full_tokens,
        selected_estimated_tokens=estimate_prompt_events_tokens(selected),
        token_budget=ctx.budget,
        protected_events=len(protected),
        windowed=True,
        reason='+'.join(ctx.reason_parts) or 'windowed',
    )


def select_prompt_events(
    events: Iterable[Event],
    llm_config: object,
    *,
    state: object | None = None,
    emergency_only: bool = False,
    tool_budget_applied: bool = False,
) -> PromptWindowResult:
    """Return a token-budget-aware prompt view preserving recent causal chunks."""
    raw_events = list(events)
    # Bind the model into a contextvar so every nested
    # ``estimate_prompt_event_tokens`` / ``_tokenize_text`` call picks
    # the right tiktoken encoding. Falling back to ``cl100k_base`` for
    # unknown models is intentional — the public signature stays stable.
    model_id = str(getattr(llm_config, 'model', '') or '')
    model_token = set_current_tokenizer_model(model_id or None)
    try:
        return _select_prompt_events_impl(
            raw_events,
            llm_config,
            state=state,
            emergency_only=emergency_only,
            tool_budget_applied=tool_budget_applied,
        )
    finally:
        reset_current_tokenizer_model(model_token)


def _select_prompt_events_impl(
    raw_events: list[Event],
    llm_config: object,
    *,
    state: object | None,
    emergency_only: bool,
    tool_budget_applied: bool,
) -> PromptWindowResult:
    ctx = _build_windowing_context(
        raw_events,
        llm_config,
        state=state,
        emergency_only=emergency_only,
        tool_budget_applied=tool_budget_applied,
    )

    if ctx.should_window or emergency_only:
        _inject_working_set(ctx, raw_events)

    if not ctx.should_window:
        return _result(
            events=ctx.event_list,
            original_events=ctx.original_event_count,
            estimated_tokens=ctx.full_tokens,
            selected_estimated_tokens=ctx.full_tokens,
            token_budget=ctx.budget,
            protected_events=0,
            windowed=False,
            reason='within_budget',
        )

    protected = _protected_summary_events(ctx.event_list)
    selected_chunks, _, _ = _select_causal_chunks(ctx, protected)
    result = _build_windowed_result(ctx, protected, selected_chunks, llm_config)
    if emergency_only and result.selected_events < DEFAULT_EMERGENCY_PROMPT_MIN_EVENTS:
        from backend.core.logging.logger import app_logger as logger

        logger.warning(
            'Emergency prompt window selected only %d/%d events (min=%d); '
            'post-boundary tail may still exceed budget',
            result.selected_events,
            result.original_events,
            DEFAULT_EMERGENCY_PROMPT_MIN_EVENTS,
        )
    return result


def _tokenize_text(text, model: str | None = None):
    if not text:
        return 0
    if model is None:
        model = _CURRENT_MODEL.get()
    tokenizer, _encoding = _tokenizer_for_model(model)
    if tokenizer is not None:
        try:
            return max(1, len(tokenizer.encode(text)))
        except Exception:
            pass
    # Heuristic fallback. The ratio is content-dependent (code/JSON
    # tokenize denser than prose) but is far better than the previous
    # loose ``len // 4`` when tiktoken is unavailable for a model.
    if model is not None:
        try:
            _, _enc = _tokenizer_for_model(model)
        except Exception:
            _enc = 'cl100k_base'
    else:
        _enc = 'cl100k_base'
    # Empirical average chars/token for English/code/JSON under cl100k_base.
    return max(1, len(text) // 4)


def _cache_token(fp, tokens):
    """LRU-cache *tokens* keyed by *fp* (fingerprint).

    Evicts the LEAST-recently-used single entry instead of wiping the
    whole map — the previous ``_EVENT_TOKEN_CACHE.clear()`` caused a
    thundering-herd re-tokenization across all in-flight agent loops.
    """
    with _EVENT_TOKEN_CACHE_LOCK:
        existing = _EVENT_TOKEN_CACHE.get(fp)
        if existing is not None:
            _EVENT_TOKEN_CACHE.move_to_end(fp)
            return
        _EVENT_TOKEN_CACHE[fp] = tokens
        while len(_EVENT_TOKEN_CACHE) > _EVENT_TOKEN_CACHE_MAX:
            _EVENT_TOKEN_CACHE.popitem(last=False)


def _event_token_cache_get(fp: str) -> int | None:
    with _EVENT_TOKEN_CACHE_LOCK:
        value = _EVENT_TOKEN_CACHE.get(fp)
        if value is not None:
            _EVENT_TOKEN_CACHE.move_to_end(fp)
        return value


def estimate_event_tokens(event: Event, model: str | None = None) -> int:
    """Best-effort token estimate for a single event (cached by fingerprint)."""
    content = getattr(event, 'content', None)
    if isinstance(content, str) and content.strip() == _MASKED_PLACEHOLDER:
        return 4
    fp = event_fingerprint(event)
    cached = _event_token_cache_get(fp)
    if cached is not None:
        return cached
    tokens = _tokenize_text(_event_payload_text(event), model=model)
    _cache_token(fp, tokens)
    return tokens


def estimate_events_tokens(events: Iterable[Event], model: str | None = None) -> int:
    """Best-effort token estimate for event payloads."""
    total = 0
    for event in events:
        total += estimate_event_tokens(event, model=model)
    if total > 0:
        return total
    text = '\n'.join(_event_payload_text(event) for event in events)
    return _tokenize_text(text, model=model)


def estimate_prompt_event_tokens(event: Event, model: str | None = None) -> int:
    """Estimate tokens for the model-visible rendering of one event."""
    content = getattr(event, 'content', None)
    if isinstance(content, str) and content.strip() == _MASKED_PLACEHOLDER:
        return 4
    return _tokenize_text(_event_prompt_payload_text(event), model=model)


def estimate_prompt_events_tokens(
    events: Iterable[Event],
    model: str | None = None,
) -> int:
    """Estimate tokens for the model-visible rendering of event history.

    If *model* is not provided, the active context-var (set via
    :func:`set_current_tokenizer_model`) is used. This keeps the public
    signature stable while letting higher-level callers (prompt window,
    context budget) opt in to model-aware counting.
    """
    total = 0
    for event in events:
        total += estimate_prompt_event_tokens(event, model=model)
    return total if total > 0 else 1


def set_current_tokenizer_model(model: str | None) -> Any:
    """Bind *model* to a contextvar so nested estimator calls pick the
    correct tiktoken encoding.

    Returns a token usable with :func:`reset_current_tokenizer_model` to
    restore the previous value (useful in async code).
    """
    return _CURRENT_MODEL.set(model or '')


def reset_current_tokenizer_model(token: Any) -> None:
    _CURRENT_MODEL.reset(token)


def event_fingerprint(event: Event) -> str:
    """Stable fingerprint for prompt-window/cache diagnostics."""
    payload = _event_payload_text(event)
    digest = hashlib.sha1(
        payload.encode('utf-8', 'ignore'), usedforsecurity=False
    ).hexdigest()[:16]
    event_id = getattr(event, 'id', None)
    return f'{type(event).__name__}:{event_id}:{digest}'


def _history_token_budget(
    llm_config: object,
    *,
    state: object | None = None,
) -> int | None:
    explicit = _positive_int_attr(llm_config, 'prompt_history_token_budget', None)
    if explicit is not None:
        return explicit
    limits = limits_from_config(llm_config, unknown_default=True)
    usable_input = limits.usable_input_tokens
    if usable_input is None:
        return None
    reserve = _fixed_prompt_reserve_tokens(state)
    if reserve > 0:
        usable_input = max(1, usable_input - reserve)
    ratio = _optional_float_attr(llm_config, 'prompt_history_budget_ratio')
    if ratio is not None:
        usable_input = int(usable_input * max(0.05, min(0.95, ratio)))
    model = str(getattr(llm_config, 'model', '') or '')
    factor, _ = model_token_correction(model)
    return max(1, int(usable_input / factor))


def _fixed_prompt_reserve_tokens(state: object | None) -> int:
    if state is None:
        return 0
    extra = getattr(state, 'extra_data', None)
    if not isinstance(extra, dict):
        return 0
    raw = extra.get('prompt_token_accounting')
    if not isinstance(raw, dict):
        return 0
    total = 0
    for key in ('static_prompt_tokens', 'tool_schema_tokens', 'context_packet_tokens'):
        value = raw.get(key)
        if value is None or isinstance(value, bool):
            continue
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            continue
        if parsed > 0:
            total += parsed
    return total


def _prompt_history_max_events(llm_config: object) -> int | None:
    explicit = _positive_int_attr(llm_config, 'prompt_history_max_events', None)
    if explicit is not None:
        return explicit
    model = str(getattr(llm_config, 'model', '') or '')
    limits = limits_from_config(llm_config, unknown_default=False)
    if model_is_small(model) or limits.source in {
        'unknown',
        'unknown_model',
        'uncataloged_model',
    }:
        return _DEFAULT_MAX_EVENTS
    return None


def _is_nonempty_user_message(event):
    return (
        isinstance(event, MessageAction)
        and event.source == EventSource.USER
        and bool((event.content or '').strip())
    )


def _find_key_user_messages(events):
    first_user = None
    last_user = None
    for event in events:
        if _is_nonempty_user_message(event):
            if first_user is None:
                first_user = event
            last_user = event
    return first_user, last_user


def _find_recent_user_messages(events, *, limit: int) -> list[Event]:
    from backend.context.prompt.user_turns import PROTECTED_RECENT_USER_MESSAGE_COUNT

    count = limit if limit > 0 else PROTECTED_RECENT_USER_MESSAGE_COUNT
    recent: list[Event] = []
    for event in reversed(events):
        if not _is_nonempty_user_message(event):
            continue
        recent.append(event)
        if len(recent) >= count:
            break
    return list(reversed(recent))


def _add_key_event(protected, seen_ids, event):
    if event is not None and id(event) not in seen_ids:
        protected.append(event)
        seen_ids.add(id(event))


def _condensation_content(event):
    return (getattr(event, 'content', '') or '').strip()


def _is_valid_condensation_event(event, seen_ids):
    content = _condensation_content(event)
    if not content or content == _MASKED_PLACEHOLDER:
        return False
    if '<CONTEXT_PACKET>' in content or '<CANONICAL_TASK_STATE>' in content:
        return False
    if '<DURABLE_WORKING_SET>' in content:
        return False
    if '<POST_COMPACT_RESTORE>' in content or '<RESTORED_CONTEXT>' in content:
        return False
    if id(event) in seen_ids:
        return False
    return True


def _collect_condensation_events(events, seen_ids):
    latest = None
    for event in reversed(events):
        if not isinstance(event, AgentCondensationObservation):
            continue
        if not _is_valid_condensation_event(event, seen_ids):
            continue
        latest = event
        break
    if latest is None:
        return []
    seen_ids.add(id(latest))
    return [latest]


def _event_type_name(event: Event | None) -> str:
    return type(event).__name__ if event is not None else ''


def _has_task_plan(event: Event) -> bool:
    task_list = getattr(event, 'task_list', None)
    return isinstance(task_list, list) and bool(task_list)


def _is_file_mutation_event(event: Event) -> bool:
    return _event_type_name(event) in (
        'FileEditAction',
        'FileEditObservation',
    )


def _is_test_observation(event: Event) -> bool:
    if _event_type_name(event) != 'CmdOutputObservation':
        return False
    command = str(getattr(event, 'command', '') or '')
    if not command:
        return False
    try:
        from backend.validation.command_classification import is_test_run_command

        return is_test_run_command(command)
    except Exception:
        lowered = command.casefold()
        return any(token in lowered for token in ('pytest', 'npm test', 'cargo test'))


def _collect_operational_anchor_events(events: list[Event], seen_ids: set[int]):
    anchors: list[Event] = []
    latest_task_tracker: Event | None = None
    latest_test: Event | None = None
    file_mutations: list[Event] = []
    for event in reversed(events):
        name = _event_type_name(event)
        if (
            latest_task_tracker is None
            and name in ('TaskTrackingAction', 'TaskTrackingObservation')
            and _has_task_plan(event)
        ):
            latest_task_tracker = event
        if latest_test is None and _is_test_observation(event):
            latest_test = event
        if _is_file_mutation_event(event) and len(file_mutations) < 8:
            file_mutations.append(event)
        if latest_task_tracker and latest_test and len(file_mutations) >= 8:
            break
    for event in [latest_task_tracker, latest_test, *reversed(file_mutations)]:
        _add_key_event(anchors, seen_ids, event)
    return anchors


def _protected_summary_events(events: list[Event]) -> list[Event]:
    from backend.context.prompt.user_turns import PROTECTED_RECENT_USER_MESSAGE_COUNT

    protected: list[Event] = []
    seen_user_ids: set[int] = set()
    first_user, _last_user = _find_key_user_messages(events)
    for user_event in _find_recent_user_messages(
        events, limit=PROTECTED_RECENT_USER_MESSAGE_COUNT
    ):
        _add_key_event(protected, seen_user_ids, user_event)
    _add_key_event(protected, seen_user_ids, first_user)
    for event in events:
        if isinstance(event, AgentCondensationObservation):
            content = _condensation_content(event)
            if '<CONTEXT_PACKET>' in content:
                _add_key_event(protected, seen_user_ids, event)
    protected.extend(_collect_condensation_events(events, seen_user_ids))
    protected.extend(_collect_operational_anchor_events(events, seen_user_ids))
    return protected


def _required_tail_ids(chunks, min_tool_loops):
    required_tail = chunks[-min_tool_loops:]
    return {id(event) for chunk in required_tail for event in chunk}


def _tail_already_present(selected, required_ids):
    selected_ids = {id(event) for event in selected}
    return required_ids.issubset(selected_ids)


def _rebuild_with_required(all_events, protected_ids, required_ids):
    keep_ids = protected_ids | required_ids
    return [event for event in all_events if id(event) in keep_ids]


def _enforce_min_tool_loops(
    selected: list[Event],
    all_events: list[Event],
    protected: list[Event],
    *,
    min_tool_loops: int,
) -> list[Event]:
    """Ensure at least *min_tool_loops* recent action→observation chunks remain."""
    if min_tool_loops <= 0:
        return selected
    protected_ids = _event_id_set(protected)
    chunks = _non_protected_chunks(all_events, protected_ids)
    if len(chunks) <= min_tool_loops:
        return selected
    required_ids = _required_tail_ids(chunks, min_tool_loops)
    if _tail_already_present(selected, required_ids):
        return selected
    return _rebuild_with_required(all_events, protected_ids, required_ids)


def _build_token_tail(chunks, protected, budget, min_tail_tokens):
    tail: list[Event] = []
    tail_tokens = estimate_prompt_events_tokens(protected)
    for chunk in reversed(chunks):
        chunk_tokens = estimate_prompt_events_tokens(chunk)
        if tail and tail_tokens + chunk_tokens > budget:
            break
        tail = chunk + tail
        tail_tokens += chunk_tokens
        if tail_tokens >= min_tail_tokens:
            break
    return tail


def _missing_tail_events(tail, selected):
    selected_ids = {id(event) for event in selected}
    return [event for event in tail if id(event) not in selected_ids]


def _combine_protected_and_tail(protected, selected, protected_ids, missing):
    merged = list(protected) + [
        event for event in selected if id(event) not in protected_ids
    ]
    merged.extend(missing)
    return _dedupe_events_preserve_order(merged)


def _merge_tail_into_selection(selected, protected, tail, protected_ids):
    missing = _missing_tail_events(tail, selected)
    if not missing:
        return selected
    return _combine_protected_and_tail(protected, selected, protected_ids, missing)


def _enforce_min_tail_tokens(
    selected: list[Event],
    all_events: list[Event],
    protected: list[Event],
    *,
    budget: int,
    min_tail_tokens: int,
) -> list[Event]:
    """Grow the tail until recent causal chunks reach *min_tail_tokens*."""
    if min_tail_tokens <= 0:
        return selected
    if estimate_prompt_events_tokens(selected) >= min(min_tail_tokens, budget):
        return selected
    protected_ids = _event_id_set(protected)
    chunks = _non_protected_chunks(all_events, protected_ids)
    if not chunks:
        return selected
    tail = _build_token_tail(chunks, protected, budget, min_tail_tokens)
    if not tail:
        return selected
    return _merge_tail_into_selection(selected, protected, tail, protected_ids)


def _dedupe_events_preserve_order(events: list[Event]) -> list[Event]:
    seen: set[int] = set()
    ordered: list[Event] = []
    for event in events:
        key = id(event)
        if key in seen:
            continue
        seen.add(key)
        ordered.append(event)
    return ordered


def _split_protected_and_removable(selected, protected_ids):
    protected_events = [event for event in selected if id(event) in protected_ids]
    removable = [event for event in selected if id(event) not in protected_ids]
    return protected_events, removable


def _truncate_latest_if_needed(chunk, kept_tokens, budget):
    chunk_tokens = estimate_prompt_events_tokens(chunk)
    if kept_tokens + chunk_tokens > budget:
        chunk = _truncate_chunk_to_budget(chunk, max(1, budget - kept_tokens))
        chunk_tokens = estimate_prompt_events_tokens(chunk)
    return chunk, chunk_tokens


def _build_kept_chunks(chunks, protected_tokens, budget):
    kept_chunks: list[list[Event]] = []
    kept_tokens = protected_tokens
    for chunk in reversed(chunks):
        if not kept_chunks:
            chunk, chunk_tokens = _truncate_latest_if_needed(chunk, kept_tokens, budget)
            kept_chunks.append(chunk)
            kept_tokens += chunk_tokens
        else:
            chunk_tokens = estimate_prompt_events_tokens(chunk)
            if kept_tokens + chunk_tokens <= budget:
                kept_chunks.append(chunk)
                kept_tokens += chunk_tokens
    kept_chunks.reverse()
    return kept_chunks


def _flatten_chunks(chunks):
    return [event for chunk in chunks for event in chunk]


def _removable_events(events, protected_ids):
    return [event for event in events if id(event) not in protected_ids]


def _shrink_once(result, protected_events, protected_tokens, tail, budget):
    remaining = max(1, budget - protected_tokens)
    truncated_tail = _truncate_chunk_to_budget(tail, remaining)
    result = protected_events + truncated_tail
    if estimate_prompt_events_tokens(result) <= budget:
        return result, False
    if not _drop_oldest_removable_unit(tail):
        return result, False
    return protected_events + tail, True


def _shrink_to_budget(
    result, protected_events, protected_tokens, protected_ids, budget
):
    while estimate_prompt_events_tokens(result) > budget:
        tail = _removable_events(result, protected_ids)
        if not tail:
            break
        result, should_continue = _shrink_once(
            result, protected_events, protected_tokens, tail, budget
        )
        if not should_continue:
            break
    return result


def _enforce_token_ceiling(
    selected: list[Event],
    budget: int,
    protected: list[Event],
) -> list[Event]:
    """Drop oldest removable causal units until the selection fits the token budget."""
    if estimate_prompt_events_tokens(selected) <= budget:
        return selected
    protected_ids = _event_id_set(protected)
    protected_events, removable = _split_protected_and_removable(
        selected, protected_ids
    )
    protected_tokens = estimate_prompt_events_tokens(protected_events)
    chunks = _causal_chunks(removable)
    kept_chunks = _build_kept_chunks(chunks, protected_tokens, budget)
    result = protected_events + _flatten_chunks(kept_chunks)
    return _shrink_to_budget(
        result, protected_events, protected_tokens, protected_ids, budget
    )


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
    """Return a prompt-only copy so windowing never mutates state.history.

    Preserves ``tool_call_metadata`` across the serialize/deserialize cycle
    so that observations retain their pairing with tool calls and are
    rendered as ``role='tool'`` rather than ``role='user'``.
    """
    # Capture metadata before serialization.
    tcm = getattr(event, '_tool_call_metadata', None)
    tr = getattr(event, '_tool_result', None)

    try:
        copied = event_from_dict(event_to_dict(event))
    except Exception:
        return copy.deepcopy(event)

    # Restore metadata if it was lost during the cycle.
    if tcm is not None and getattr(copied, '_tool_call_metadata', None) is None:
        copied._tool_call_metadata = tcm  # type: ignore[attr-defined]
    if tr is not None and getattr(copied, '_tool_result', None) is None:
        copied._tool_result = tr  # type: ignore[attr-defined]
    return copied


def _find_first_action_index(chunk):
    return next(
        (i for i, event in enumerate(chunk) if isinstance(event, Action)),
        len(chunk),
    )


def _drop_action_and_results(chunk):
    chunk.pop(0)
    while chunk and not isinstance(chunk[0], Action):
        chunk.pop(0)
    return True


def _drop_oldest_removable_unit(chunk: list[Event]) -> bool:
    """Drop the oldest causal unit without splitting an action from its results."""
    if len(chunk) <= 1:
        return False
    first_action_idx = _find_first_action_index(chunk)
    if first_action_idx > 0:
        chunk.pop(0)
        return True
    if isinstance(chunk[0], Action):
        return _drop_action_and_results(chunk)
    return False


def _collect_truncatable_events(chunk, head_chars, tail_chars):
    sized = []
    for i, event in enumerate(chunk):
        if isinstance(event, Action):
            continue
        content = getattr(event, 'content', None)
        if not isinstance(content, str) or len(content) < head_chars + tail_chars:
            continue
        sized.append((len(content), i, event))
    sized.sort(reverse=True)
    return sized


def _apply_truncations(chunk, sized, token_budget, head_chars, tail_chars, marker):
    for _size, idx, event in sized:
        if estimate_prompt_events_tokens(chunk) <= token_budget:
            break
        content = getattr(event, 'content', '')
        truncated = (
            _safe_truncate_to_chars(content, head_chars)
            + marker
            + _safe_tail_to_chars(content, tail_chars)
        )
        try:
            event.content = truncated
        except Exception:
            pass


def _safe_truncate_to_chars(text: str, max_chars: int) -> str:
    """Head-truncate at a safe boundary (newline > space > hard cut)."""
    if max_chars <= 0 or len(text) <= max_chars:
        return text[:max_chars] if max_chars >= 0 else ''
    chunk = text[:max_chars]
    lower_floor = max_chars // 2
    nl = chunk.rfind('\n')
    if nl >= lower_floor:
        return chunk[:nl]
    sp = chunk.rfind(' ')
    if sp >= lower_floor:
        return chunk[:sp]
    return chunk


def _safe_tail_to_chars(text: str, max_chars: int) -> str:
    """Tail-truncate at a safe boundary.

    Returns at most *max_chars* characters from the END of *text*,
    preferring to start at a newline or space boundary so we never
    split a JSON / Markdown / XML token mid-stream.
    """
    if max_chars <= 0 or len(text) <= max_chars:
        return text[-max_chars:] if max_chars > 0 else ''
    tail = text[-max_chars:]
    lower_floor = max_chars // 2
    nl = tail.find('\n')
    if nl >= 0 and nl <= lower_floor:
        return tail[nl + 1 :]
    sp = tail.find(' ')
    if sp >= 0 and sp <= lower_floor:
        return tail[sp + 1 :]
    return tail


def _truncate_large_observations(
    chunk: list[Event],
    token_budget: int,
    head_chars: int,
    tail_chars: int,
    marker: str,
) -> None:
    sized = _collect_truncatable_events(chunk, head_chars, tail_chars)
    _apply_truncations(chunk, sized, token_budget, head_chars, tail_chars, marker)


def _drop_oldest_units_until_fit(
    chunk: list[Event],
    token_budget: int,
) -> None:
    while len(chunk) > 1 and estimate_prompt_events_tokens(chunk) > token_budget:
        if not _drop_oldest_removable_unit(chunk):
            break


def _shrink_one_observation(chunk, marker):
    for event in chunk:
        if isinstance(event, Action):
            continue
        content = getattr(event, 'content', None)
        if not isinstance(content, str) or len(content) <= 80:
            continue
        head_budget = max(80, len(content) // 2)
        event.content = _safe_truncate_to_chars(content, head_budget) + marker
        return True
    return False


def _aggressively_shrink_observations(
    chunk: list[Event],
    token_budget: int,
    marker: str,
) -> None:
    while estimate_prompt_events_tokens(chunk) > token_budget:
        if not _shrink_one_observation(chunk, marker):
            break


def _fallback_single_event(chunk: list[Event], original: list[Event]) -> list[Event]:
    if not chunk and original:
        for event in reversed(original):
            if isinstance(event, Action):
                return [_copy_event_for_prompt(event)]
        return [_copy_event_for_prompt(original[-1])]
    return chunk


def _copy_events_for_prompt(chunk):
    return [_copy_event_for_prompt(event) for event in chunk]


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
    chunk = _copy_events_for_prompt(chunk)

    _TRUNCATION_MARKER = '\n\n[... truncated to fit context window ...]\n\n'
    _HEAD_CHARS = 500
    _TAIL_CHARS = 500

    if estimate_prompt_events_tokens(chunk) <= token_budget:
        return chunk

    _truncate_large_observations(
        chunk, token_budget, _HEAD_CHARS, _TAIL_CHARS, _TRUNCATION_MARKER
    )
    if estimate_prompt_events_tokens(chunk) <= token_budget:
        return chunk

    _drop_oldest_units_until_fit(chunk, token_budget)
    _aggressively_shrink_observations(chunk, token_budget, _TRUNCATION_MARKER)

    return _fallback_single_event(chunk, original)


def _event_payload_text(event: Event) -> str:
    try:
        return json.dumps(event_to_dict(event), default=str, sort_keys=True)
    except Exception:
        return str(
            getattr(event, 'message', '') or getattr(event, 'content', '') or event
        )


def _event_prompt_payload_text(event: Event) -> str:
    parts: list[str] = []
    event_id = getattr(event, 'id', None)
    if event_id is not None:
        parts.append(f'{type(event).__name__} id={event_id}')
    else:
        parts.append(type(event).__name__)

    for attr in (
        'message',
        'content',
        'thought',
        'command',
        'path',
        'query',
        'code',
        'task_list',
        'tool_result',
    ):
        try:
            value = getattr(event, attr, None)
        except Exception:
            continue
        if callable(value):
            try:
                value = value()
            except Exception:
                value = None
        if value is None:
            continue
        if isinstance(value, str):
            text = value.strip()
        else:
            try:
                text = json.dumps(value, default=str, sort_keys=True)
            except Exception:
                text = str(value)
        if text and text not in parts:
            parts.append(text)

    if len(parts) <= 1:
        fallback = str(event)
        if fallback:
            parts.append(fallback)
    return '\n'.join(parts)


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
        fingerprint_payload.encode('utf-8', 'ignore'),
        usedforsecurity=False,
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


def _parse_non_negative_int(value, default):
    if isinstance(value, str):
        try:
            parsed = int(value)
        except ValueError:
            return default
        return parsed if parsed >= 0 else default
    return default


def _non_negative_int_attr(obj: object, name: str, default: int) -> int:
    value = getattr(obj, name, default)
    if isinstance(value, bool):
        return default
    if isinstance(value, int) and value >= 0:
        return value
    return _parse_non_negative_int(value, default)


def _parse_positive_int(value, default):
    if isinstance(value, str):
        try:
            parsed = int(value)
        except ValueError:
            return default
        return parsed if parsed > 0 else default
    return default


def _positive_int_attr(obj: object, name: str, default: int | None) -> int | None:
    value = getattr(obj, name, default)
    if isinstance(value, bool):
        return default
    if isinstance(value, int) and value > 0:
        return value
    return _parse_positive_int(value, default)


def _optional_float_attr(obj: object, name: str) -> float | None:
    value = getattr(obj, name, None)
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (float, int)):
        return float(value)
    if isinstance(value, str) and value.strip():
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _bool_attr(obj: object, name: str, default: bool) -> bool:
    value = getattr(obj, name, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() not in {'0', 'false', 'no', 'off'}
    return default


@lru_cache(maxsize=4)
def _tokenizer(encoding_name: str = 'cl100k_base') -> Any | None:
    """Return a tiktoken encoding by name (cached per encoding).

    ``cl100k_base`` is the historical default (GPT-4 / GPT-3.5). For newer
    OpenAI models (``o200k_base``) or to match Anthropic/Google
    tokenization more closely, prefer :func:`_tokenizer_for_model`.
    """
    try:
        import tiktoken  # type: ignore

        return tiktoken.get_encoding(encoding_name)
    except Exception:
        return None


def _tokenizer_for_model(model: str | None) -> tuple[Any | None, str]:
    """Return ``(tokenizer, encoding_name)`` best matching *model*.

    Falls back to ``cl100k_base`` for unknown or OpenAI models. The
    returned ``encoding_name`` is what callers should log or persist in
    telemetry.
    """
    name = (model or '').strip().lower()
    if not name:
        return _tokenizer('cl100k_base'), 'cl100k_base'
    # Newer OpenAI generations switched to o200k_base (GPT-4o, o1, o3, o4).
    if any(needle in name for needle in ('gpt-4o', 'o1', 'o3', 'o4', 'gpt-5')):
        return _tokenizer('o200k_base'), 'o200k_base'
    # Legacy OpenAI (GPT-4, GPT-3.5) and the safe default for unknown.
    return _tokenizer('cl100k_base'), 'cl100k_base'


__all__ = [
    'PromptWindowResult',
    'estimate_event_tokens',
    'estimate_events_tokens',
    'estimate_prompt_event_tokens',
    'estimate_prompt_events_tokens',
    'event_fingerprint',
    'select_prompt_events',
]
