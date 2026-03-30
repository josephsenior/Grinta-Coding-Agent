"""Tests for backend.core.config.compactor_config - compactor config models and factories."""

import pytest
from pydantic import ValidationError

from backend.core.config.compactor_config import (
    AmortizedPruningCompactorConfig,
    BrowserOutputCompactorConfig,
    CompactorPipelineConfig,
    ConversationWindowCompactorConfig,
    NoOpCompactorConfig,
    ObservationMaskingCompactorConfig,
    RecentEventsCompactorConfig,
    SmartCompactorConfig,
    compactor_config_from_toml_section,
    create_compactor_config,
)


# ── Config model defaults ─────────────────────────────────────────────


class TestNoOpCompactorConfig:
    def test_default(self):
        c = NoOpCompactorConfig()
        assert c.type == "noop"

    def test_rejects_extra_fields(self):
        with pytest.raises(ValidationError):
            NoOpCompactorConfig(**{"type": "noop", "extra_field": "bad"})


class TestObservationMaskingConfig:
    def test_default_attention_window(self):
        c = ObservationMaskingCompactorConfig()
        assert c.type == "observation_masking"
        assert c.attention_window >= 1

    def test_custom_window(self):
        c = ObservationMaskingCompactorConfig(attention_window=10)
        assert c.attention_window == 10

    def test_rejects_zero_window(self):
        with pytest.raises(ValidationError):
            ObservationMaskingCompactorConfig(attention_window=0)


class TestBrowserOutputCompactorConfig:
    def test_default(self):
        c = BrowserOutputCompactorConfig()
        assert c.type == "browser_output_masking"
        assert c.attention_window >= 1


class TestRecentEventsConfig:
    def test_defaults(self):
        c = RecentEventsCompactorConfig()
        assert c.type == "recent"
        assert c.keep_first >= 0
        assert c.max_events >= 1

    def test_custom_values(self):
        c = RecentEventsCompactorConfig(keep_first=5, max_events=50)
        assert c.keep_first == 5
        assert c.max_events == 50

    def test_rejects_negative_keep_first(self):
        with pytest.raises(ValidationError):
            RecentEventsCompactorConfig(keep_first=-1)


class TestAmortizedPruningConfig:
    def test_defaults(self):
        c = AmortizedPruningCompactorConfig()
        assert c.type == "amortized"
        assert c.max_size >= 2
        assert c.keep_first >= 0
        assert c.token_budget is None

    def test_with_token_budget(self):
        c = AmortizedPruningCompactorConfig(token_budget=4096)
        assert c.token_budget == 4096


class TestCompactorPipelineConfig:
    def test_empty_pipeline(self):
        c = CompactorPipelineConfig()
        assert c.type == "pipeline"
        assert c.compactors == []

    def test_legacy_condensers_field_rejected(self):
        with pytest.raises(ValidationError):
            CompactorPipelineConfig.model_validate({"condensers": [{"type": "noop"}]})


class TestConversationWindowConfig:
    def test_default(self):
        c = ConversationWindowCompactorConfig()
        assert c.type == "conversation_window"


class TestSmartCompactorConfig:
    def test_defaults(self):
        c = SmartCompactorConfig()
        assert c.type == "smart"
        assert c.llm_config is None
        assert c.max_size >= 2
        assert c.importance_threshold >= 0.0
        assert c.importance_threshold <= 1.0
        assert c.recency_bonus_window >= 1

    def test_rejects_bad_importance(self):
        with pytest.raises(ValidationError):
            SmartCompactorConfig(importance_threshold=1.5)

    def test_rejects_bad_importance_negative(self):
        with pytest.raises(ValidationError):
            SmartCompactorConfig(importance_threshold=-0.1)


# ── create_compactor_config ──────────────────────────────────────────


class TestCreateCompactorConfig:
    def test_noop(self):
        cfg = create_compactor_config("noop", {"type": "noop"})
        assert isinstance(cfg, NoOpCompactorConfig)

    def test_recent(self):
        cfg = create_compactor_config("recent", {"type": "recent", "max_events": 100})
        assert isinstance(cfg, RecentEventsCompactorConfig)
        assert cfg.max_events == 100

    def test_amortized(self):
        cfg = create_compactor_config(
            "amortized", {"type": "amortized", "max_size": 50}
        )
        assert isinstance(cfg, AmortizedPruningCompactorConfig)
        assert cfg.max_size == 50

    def test_observation_masking(self):
        cfg = create_compactor_config(
            "observation_masking", {"type": "observation_masking"}
        )
        assert isinstance(cfg, ObservationMaskingCompactorConfig)

    def test_conversation_window(self):
        cfg = create_compactor_config(
            "conversation_window", {"type": "conversation_window"}
        )
        assert isinstance(cfg, ConversationWindowCompactorConfig)

    def test_smart(self):
        cfg = create_compactor_config("smart", {"type": "smart"})
        assert isinstance(cfg, SmartCompactorConfig)

    def test_unknown_type_raises(self):
        with pytest.raises(ValueError, match="Unknown compactor type"):
            create_compactor_config("nonexistent", {"type": "nonexistent"})

    def test_invalid_data_raises(self):
        with pytest.raises(ValueError, match="Validation failed"):
            create_compactor_config("recent", {"type": "recent", "max_events": -1})


# ── compactor_config_from_toml_section ───────────────────────────────


class TestCompactorConfigFromTomlSection:
    def test_noop_section(self):
        result = compactor_config_from_toml_section({"type": "noop"})
        assert "compactor" in result
        assert isinstance(result["compactor"], NoOpCompactorConfig)

    def test_defaults_to_smart(self):
        """When no type is specified, defaults to 'smart'."""
        result = compactor_config_from_toml_section({})
        assert "compactor" in result
        assert isinstance(result["compactor"], SmartCompactorConfig)

    def test_invalid_config_falls_back_to_noop(self):
        """Invalid config should produce NoOpCompactorConfig with warning."""
        result = compactor_config_from_toml_section(
            {
                "type": "recent",
                "max_events": -1,  # Invalid
            }
        )
        assert "compactor" in result
        assert isinstance(result["compactor"], NoOpCompactorConfig)

    def test_llm_config_missing_falls_back_to_noop(self):
        """LLM compactor referencing missing config should fall back to NoOp."""
        result = compactor_config_from_toml_section(
            {"type": "llm", "llm_config": "nonexistent_llm"},
            llm_configs={"other_llm": object()},
        )
        assert "compactor" in result
        assert isinstance(result["compactor"], NoOpCompactorConfig)

    def test_recent_section(self):
        result = compactor_config_from_toml_section(
            {
                "type": "recent",
                "max_events": 200,
                "keep_first": 3,
            }
        )
        cfg = result["compactor"]
        assert isinstance(cfg, RecentEventsCompactorConfig)
        assert cfg.max_events == 200
        assert cfg.keep_first == 3
