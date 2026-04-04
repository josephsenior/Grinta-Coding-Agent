"""Unit tests for backend.inference.cost_tracker."""

from __future__ import annotations

from types import SimpleNamespace
from typing import cast
from unittest.mock import MagicMock, patch

import pytest

from backend.core.config import LLMConfig
from backend.inference.cost_tracker import (
    get_completion_cost,
    record_llm_cost_from_metrics,
    record_llm_cost_from_response,
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


# ---------------------------------------------------------------------------
# record_llm_cost_from_metrics
# ---------------------------------------------------------------------------


class TestRecordLLMCostFromMetrics:
    def test_records_accumulated_cost(self):
        metrics = cast(Metrics, SimpleNamespace(accumulated_cost=1.23))
        mock_record = MagicMock()
        with patch.dict(
            'sys.modules',
            {
                'backend.telemetry.cost_recording': MagicMock(
                    record_llm_cost=mock_record
                )
            },
        ):
            record_llm_cost_from_metrics('user:42', metrics)
        mock_record.assert_called_once_with('user:42', 1.23)

    def test_zero_cost_not_recorded(self):
        metrics = cast(Metrics, SimpleNamespace(accumulated_cost=0.0))
        # Should not raise even if the import is missing
        record_llm_cost_from_metrics('user:1', metrics)

    def test_missing_import_handled_gracefully(self):
        """If the telemetry module is absent, no error is raised."""
        metrics = cast(Metrics, SimpleNamespace(accumulated_cost=5.0))
        with patch(
            'builtins.__import__',
            side_effect=ImportError('no module'),
        ):
            # Should not raise
            record_llm_cost_from_metrics('user:1', metrics)


# ---------------------------------------------------------------------------
# record_llm_cost_from_response
# ---------------------------------------------------------------------------


class TestRecordLLMCostFromResponse:
    @patch('backend.inference.cost_tracker.get_completion_cost', return_value=0.50)
    def test_records_cost_from_usage(self, mock_cost):
        response = {'usage': {'prompt_tokens': 100, 'completion_tokens': 50}}
        with patch('backend.telemetry.cost_recording.record_llm_cost') as mock_record:
            record_llm_cost_from_response('ip:127', response, 'gpt-4o')
        mock_cost.assert_called_once()
        mock_record.assert_called_once_with('ip:127', 0.50)

    def test_missing_usage_does_not_crash(self):
        """Empty response dict should not raise."""
        record_llm_cost_from_response('ip:1', {}, 'gpt-4o')

    def test_import_error_swallowed(self):
        response = {'usage': {'prompt_tokens': 100, 'completion_tokens': 50}}
        with patch(
            'builtins.__import__',
            side_effect=ImportError('gone'),
        ):
            record_llm_cost_from_response('u:1', response, 'gpt-4o')
