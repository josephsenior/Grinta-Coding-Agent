"""Tests for AmortizedPruningCompactor."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from backend.context.compactor.compactor import Compaction
from backend.context.compactor.strategies.amortized_pruning_compactor import (
    AmortizedPruningCompactor,
)
from backend.context.view import View
from backend.core.config.compactor_config import AmortizedPruningCompactorConfig
from backend.ledger.event import Event


def _event(eid: int) -> Event:
    e = Event()
    e.id = eid
    return e


def test_amortized_constructor_validation() -> None:
    with pytest.raises(ValueError, match='keep_first'):
        AmortizedPruningCompactor(max_size=10, keep_first=6)
    with pytest.raises(ValueError, match='negative'):
        AmortizedPruningCompactor(max_size=20, keep_first=-1)


def test_should_compact_when_over_max() -> None:
    c = AmortizedPruningCompactor(max_size=4, keep_first=1)
    v = View(events=[_event(i) for i in range(5)])
    assert c.should_compact(v) is True
    assert c.should_compact(View(events=[_event(1)])) is False


async def test_get_compaction_prunes_middle_events() -> None:
    c = AmortizedPruningCompactor(max_size=6, keep_first=1)
    events = [_event(i) for i in range(10)]
    view = View(events=events)
    comp = await c.get_compaction(view)
    assert isinstance(comp, Compaction)
    assert len(comp.action.pruned_event_ids) >= 1  # type: ignore[arg-type]
    assert comp.action.summary is not None
    assert 'Deterministic compaction pruned' in comp.action.summary
    assert comp.action.summary_offset == 1


async def test_compact_returns_view_when_under_threshold() -> None:
    c = AmortizedPruningCompactor(max_size=100, keep_first=0)
    v = View(events=[_event(1)])
    out = await c.compact(v)
    assert out is v


def test_from_config_builds_compactor() -> None:
    cfg = AmortizedPruningCompactorConfig(max_size=50, keep_first=5, token_budget=None)
    reg = MagicMock()
    comp = AmortizedPruningCompactor.from_config(cfg, reg)
    assert comp.max_size == 50
    assert comp.keep_first == 5
