"""Unit tests for backend.inference.cost_tracker."""

from __future__ import annotations

from types import SimpleNamespace
from typing import cast
from unittest.mock import MagicMock, patch

import pytest

from backend.core.config import LLMConfig
from backend.inference.cost_tracker import (
    get_completion_cost,
)
from backend.inference.metrics import Metrics

# ---------------------------------------------------------------------------
# get_completion_cost — config overrides
# ---------------------------------------------------------------------------


class TestGetCompletionCostConfig:
    """Test cost calculation with explicit per-token config overrides."""

    def test_config_override_takes_precedence(self):
        """When config supplies both cost fields, they should be used."""
        cfg = cast(
            LLMConfig,
            SimpleNamespace(input_cost_per_token=0.001, output_cost_per_token=0.002),
        )
        cost = get_completion_cost('any-model', 100, 50, config=cfg)
        assert cost == pytest.approx(100 * 0.001 + 50 * 0.002)

    def test_config_override_with_zero_tokens(self):
        cfg = cast(
            LLMConfig,
            SimpleNamespace(input_cost_per_token=0.001, output_cost_per_token=0.002),
        )
        assert get_completion_cost('m', 0, 0, config=cfg) == 0.0

    def test_config_partial_override_falls_through(self):
        """If only one cost field is set, config path is NOT used."""
        cfg = cast(
            LLMConfig,
            SimpleNamespace(input_cost_per_token=0.001, output_cost_per_token=None),
        )
        # Should fall through to catalog lookup
        with patch(
            'backend.inference.cost_tracker.get_pricing',
            return_value={'input': 10.0, 'output': 30.0},
        ):
            cost = get_completion_cost('some-model', 1_000_000, 500_000, config=cfg)
        assert cost == pytest.approx(10.0 + 15.0)

    def test_no_config_uses_catalog(self):
        with patch(
            'backend.inference.cost_tracker.get_pricing',
            return_value={'input': 3.0, 'output': 15.0},
        ):
            cost = get_completion_cost('gpt-4o', 1_000_000, 1_000_000)
        assert cost == pytest.approx(3.0 + 15.0)


# ---------------------------------------------------------------------------
# get_completion_cost — catalog fallback and zero
# ---------------------------------------------------------------------------


class TestGetCompletionCostCatalog:
    def test_no_pricing_returns_zero(self):
        with patch('backend.inference.cost_tracker.get_pricing', return_value=None):
            assert get_completion_cost('unknown-model', 1000, 500) == 0.0

    def test_catalog_pricing_per_million(self):
        with patch(
            'backend.inference.cost_tracker.get_pricing',
            return_value={'input': 2.0, 'output': 8.0},
        ):
            # 500k input tokens, 250k output tokens
            cost = get_completion_cost('m', 500_000, 250_000)
            expected = (500_000 / 1_000_000) * 2.0 + (250_000 / 1_000_000) * 8.0
            assert cost == pytest.approx(expected)


