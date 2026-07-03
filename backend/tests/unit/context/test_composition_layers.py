"""Tests for composition pipeline layers."""

from __future__ import annotations

import pytest

from backend.context.compactor.strategies.composition_pipeline import (
    CompositionCompactor,
)
from backend.context.compactor.strategies.layers import reactive_compact_layer
from backend.ledger.action.message import MessageAction
from backend.ledger.event import EventSource


def _events(count: int) -> list[MessageAction]:
    items: list[MessageAction] = []
    for index in range(count):
        action = MessageAction(content=f'event {index}')
        action.id = index
        action.source = EventSource.AGENT
        items.append(action)
    return items


@pytest.mark.asyncio
async def test_reactive_compact_layer_uses_secondary_cap() -> None:
    events = _events(1000)
    result = await reactive_compact_layer(events, max_events=500)
    assert len(result) == 500
    assert result[0].content == 'event 500'


def test_composition_compactor_defaults_reactive_below_snip_cap() -> None:
    compactor = CompositionCompactor(snip_max_events=1000)
    assert compactor.reactive_max_events == 500
