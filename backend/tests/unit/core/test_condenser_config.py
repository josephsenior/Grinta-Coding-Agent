"""Tests for backend.core.config.condenser_config — condenser config models and factories."""

import pytest
from pydantic import ValidationError

from backend.core.config.condenser_config import (
    AmortizedForgettingCondenserConfig,
    BrowserOutputCondenserConfig,
    CondenserPipelineConfig,
    ConversationWindowCondenserConfig,
    NoOpCondenserConfig,
    ObservationMaskingCondenserConfig,
    RecentEventsCondenserConfig,
    SmartCondenserConfig,
    condenser_config_from_toml_section,
    create_condenser_config,
)


# ── Config model defaults ─────────────────────────────────────────────


class TestNoOpCondenserConfig:
    def test_default(self):
        c = NoOpCondenserConfig()
        assert c.type == "noop"

    def test_rejects_extra_fields(self):
        with pytest.raises(ValidationError):
            NoOpCondenserConfig(type="noop", extra_field="bad")


class TestObservationMaskingConfig:
    def test_default_attention_window(self):
        c = ObservationMaskingCondenserConfig()
        assert c.type == "observation_masking"
        assert c.attention_window >= 1

    def test_custom_window(self):
        c = ObservationMaskingCondenserConfig(attention_window=10)
        assert c.attention_window == 10

    def test_rejects_zero_window(self):
        with pytest.raises(ValidationError):
            ObservationMaskingCondenserConfig(attention_window=0)


class TestBrowserOutputCondenserConfig:
    def test_default(self):
        c = BrowserOutputCondenserConfig()
        assert c.type == "browser_output_masking"
        assert c.attention_window >= 1


class TestRecentEventsConfig:
    def test_defaults(self):
        c = RecentEventsCondenserConfig()
        assert c.type == "recent"
        assert c.keep_first >= 0
        assert c.max_events >= 1

    def test_custom_values(self):
        c = RecentEventsCondenserConfig(keep_first=5, max_events=50)
        assert c.keep_first == 5
        assert c.max_events == 50

    def test_rejects_negative_keep_first(self):
        with pytest.raises(ValidationError):
            RecentEventsCondenserConfig(keep_first=-1)


class TestAmortizedForgettingConfig:
    def test_defaults(self):
        c = AmortizedForgettingCondenserConfig()
        assert c.type == "amortized"
        assert c.max_size >= 2
        assert c.keep_first >= 0
        assert c.token_budget is None

    def test_with_token_budget(self):
        c = AmortizedForgettingCondenserConfig(token_budget=4096)
        assert c.token_budget == 4096


class TestCondenserPipelineConfig:
    def test_empty_pipeline(self):
        c = CondenserPipelineConfig()
        assert c.type == "pipeline"
        assert c.condensers == []


class TestConversationWindowConfig:
    def test_default(self):
        c = ConversationWindowCondenserConfig()
        assert c.type == "conversation_window"


class TestSmartCondenserConfig:
    def test_defaults(self):
        c = SmartCondenserConfig()
        assert c.type == "smart"
        assert c.llm_config is None
        assert c.max_size >= 2
        assert c.importance_threshold >= 0.0
        assert c.importance_threshold <= 1.0
        assert c.recency_bonus_window >= 1

    def test_rejects_bad_importance(self):
        with pytest.raises(ValidationError):
            SmartCondenserConfig(importance_threshold=1.5)

    def test_rejects_bad_importance_negative(self):
        with pytest.raises(ValidationError):
            SmartCondenserConfig(importance_threshold=-0.1)


# ── create_condenser_config ──────────────────────────────────────────


class TestCreateCondenserConfig:
    def test_noop(self):
        cfg = create_condenser_config("noop", {"type": "noop"})
        assert isinstance(cfg, NoOpCondenserConfig)

    def test_recent(self):
        cfg = create_condenser_config("recent", {"type": "recent", "max_events": 100})
        assert isinstance(cfg, RecentEventsCondenserConfig)
        assert cfg.max_events == 100

    def test_amortized(self):
        cfg = create_condenser_config(
            "amortized", {"type": "amortized", "max_size": 50}
        )
        assert isinstance(cfg, AmortizedForgettingCondenserConfig)
        assert cfg.max_size == 50

    def test_observation_masking(self):
        cfg = create_condenser_config(
            "observation_masking", {"type": "observation_masking"}
        )
        assert isinstance(cfg, ObservationMaskingCondenserConfig)

    def test_conversation_window(self):
        cfg = create_condenser_config(
            "conversation_window", {"type": "conversation_window"}
        )
        assert isinstance(cfg, ConversationWindowCondenserConfig)

    def test_smart(self):
        cfg = create_condenser_config("smart", {"type": "smart"})
        assert isinstance(cfg, SmartCondenserConfig)

    def test_unknown_type_raises(self):
        with pytest.raises(ValueError, match="Unknown condenser type"):
            create_condenser_config("nonexistent", {"type": "nonexistent"})

    def test_invalid_data_raises(self):
        with pytest.raises(ValueError, match="Validation failed"):
            create_condenser_config("recent", {"type": "recent", "max_events": -1})


# ── condenser_config_from_toml_section ───────────────────────────────


class TestCondenserConfigFromTomlSection:
    def test_noop_section(self):
        result = condenser_config_from_toml_section({"type": "noop"})
        assert "condenser" in result
        assert isinstance(result["condenser"], NoOpCondenserConfig)

    def test_defaults_to_smart(self):
        """When no type is specified, defaults to 'smart'."""
        result = condenser_config_from_toml_section({})
        assert "condenser" in result
        assert isinstance(result["condenser"], SmartCondenserConfig)

    def test_invalid_config_falls_back_to_noop(self):
        """Invalid config should produce NoOpCondenserConfig with warning."""
        result = condenser_config_from_toml_section(
            {
                "type": "recent",
                "max_events": -1,  # Invalid
            }
        )
        assert "condenser" in result
        assert isinstance(result["condenser"], NoOpCondenserConfig)

    def test_llm_config_missing_falls_back_to_noop(self):
        """LLM condenser referencing missing config should fall back to NoOp."""
        result = condenser_config_from_toml_section(
            {"type": "llm", "llm_config": "nonexistent_llm"},
            llm_configs={"other_llm": object()},
        )
        assert "condenser" in result
        assert isinstance(result["condenser"], NoOpCondenserConfig)

    def test_recent_section(self):
        result = condenser_config_from_toml_section(
            {
                "type": "recent",
                "max_events": 200,
                "keep_first": 3,
            }
        )
        cfg = result["condenser"]
        assert isinstance(cfg, RecentEventsCondenserConfig)
        assert cfg.max_events == 200
        assert cfg.keep_first == 3
