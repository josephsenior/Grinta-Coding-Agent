"""Tests for fingerprinted context packet caching."""

from __future__ import annotations

from types import SimpleNamespace

from backend.context.prompt.context_packet import build_context_packet
from backend.context.prompt.context_packet_cache import (
    clear_context_packet_cache,
    compute_context_packet_cache_key,
    get_cached_context_packet,
)
from backend.ledger.action import MessageAction
from backend.ledger.event import EventSource


def _user(text: str, event_id: int) -> MessageAction:
    event = MessageAction(content=text)
    event.source = EventSource.USER
    event.id = event_id
    return event


def test_context_packet_cache_hit_on_identical_rebuild(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        'backend.context.canonical_state.canonical_state_path',
        lambda state=None: tmp_path / 'canonical_task_state.json',
    )
    clear_context_packet_cache()
    state = SimpleNamespace(session_id='session-cache-test')
    events = [_user('Implement caching', 1)]

    from backend.context.prompt import context_packet as packet_mod

    call_count = 0
    original = packet_mod._canonical_for_packet

    def _counting_canonical(history, *, state=None):
        nonlocal call_count
        call_count += 1
        return original(history, state=state)

    packet_mod._canonical_for_packet = _counting_canonical
    try:
        first = build_context_packet(events, events, state=state, char_budget=2200)
        second = build_context_packet(events, events, state=state, char_budget=2200)
    finally:
        packet_mod._canonical_for_packet = original

    assert first is not None
    assert second is not None
    assert first.content == second.content
    assert call_count == 1


def test_context_packet_cache_misses_when_history_grows(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        'backend.context.canonical_state.canonical_state_path',
        lambda state=None: tmp_path / 'canonical_task_state.json',
    )
    clear_context_packet_cache()
    state = SimpleNamespace(session_id='session-cache-miss')
    first_events = [_user('Start work', 1)]
    build_context_packet(first_events, first_events, state=state, char_budget=2200)

    grown_history = [*first_events, _user('Continue', 2)]
    key = compute_context_packet_cache_key(
        events=grown_history,
        history=grown_history,
        state=state,
        snapshot=None,
        just_compacted=False,
        char_budget=2200,
    )
    assert get_cached_context_packet(state, key) is None


def test_clear_context_packet_cache_drops_session_entry() -> None:
    from backend.context.prompt.context_packet import ContextPacket
    from backend.context.prompt.context_packet_cache import store_context_packet_cache

    clear_context_packet_cache()
    state = SimpleNamespace(session_id='session-clear')
    packet = ContextPacket(content='cached', section_lengths={'x': 1})
    store_context_packet_cache(state, 'abc', packet)
    assert get_cached_context_packet(state, 'abc') is not None
    clear_context_packet_cache('session-clear')
    assert get_cached_context_packet(state, 'abc') is None
