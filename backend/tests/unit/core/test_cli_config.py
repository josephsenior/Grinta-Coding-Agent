"""Tests for backend.core.config.cli_config — CLI configuration helpers."""

from __future__ import annotations

from argparse import Namespace
from unittest.mock import patch

import pytest

from backend.core.config.app_config import AppConfig
from backend.core.config.cli_config import (
    _load_json_config,
    apply_additional_overrides,
    apply_llm_config_override,
    get_llm_config_arg,
)
from backend.core.config.llm_config import LLMConfig

# ── _load_json_config ────────────────────────────────────────────────


class TestLoadJsonConfig:
    def test_file_not_found(self, tmp_path):
        result = _load_json_config(str(tmp_path / 'nonexistent.json'))
        assert result is None

    def test_invalid_json(self, tmp_path):
        bad_file = tmp_path / 'bad.json'
        bad_file.write_text('{{invalid json')
        result = _load_json_config(str(bad_file))
        assert result is None

    def test_valid_json(self, tmp_path):
        good_file = tmp_path / 'good.json'
        good_file.write_text('{"section": {"key": "value"}}')
        result = _load_json_config(str(good_file))
        assert result is not None
        assert result['section']['key'] == 'value'


# ── get_llm_config_arg ──────────────────────────────────────────────


class TestGetLlmConfigArg:
    def test_found_config(self, tmp_path):
        cfg_file = tmp_path / 'settings.json'
        cfg_file.write_text('{"llm_model": "gpt-4"}')
        result = get_llm_config_arg('custom', str(cfg_file))
        assert result is not None
        assert result.model == 'gpt-4'

    def test_not_found_with_empty_config(self, tmp_path):
        cfg_file = tmp_path / 'settings.json'
        cfg_file.write_text('{"agent_name": "test"}')
        result = get_llm_config_arg('missing', str(cfg_file))
        # With the fix, we now return None if no LLM keys exists in the flat schema so fallback triggers
        assert result is None

    def test_strips_bracket_prefix_and_still_returns(self, tmp_path):
        cfg_file = tmp_path / 'settings.json'
        cfg_file.write_text('{"llm_model": "claude"}')
        result = get_llm_config_arg('[llm.mymodel]', str(cfg_file))
        assert result is not None
        assert result.model == 'claude'

    def test_missing_file(self):
        result = get_llm_config_arg('any', 'nonexistent_file.json')
        assert result is None


# ── apply_additional_overrides ───────────────────────────────────────


class TestApplyAdditionalOverrides:
    def test_agent_cls_override(self):
        config = AppConfig()
        args = Namespace(
            agent_cls='CustomAgent', max_iterations=None, max_budget_per_task=None
        )
        apply_additional_overrides(config, args)
        assert config.default_agent == 'CustomAgent'

    def test_max_iterations_override(self):
        config = AppConfig()
        args = Namespace(agent_cls=None, max_iterations=50, max_budget_per_task=None)
        apply_additional_overrides(config, args)
        assert config.max_iterations == 50

    def test_max_budget_override(self):
        config = AppConfig()
        args = Namespace(agent_cls=None, max_iterations=None, max_budget_per_task=10.0)
        apply_additional_overrides(config, args)
        assert config.max_budget_per_task == 10.0

    def test_no_overrides(self):
        config = AppConfig()
        original_agent = config.default_agent
        original_iter = config.max_iterations
        args = Namespace()
        apply_additional_overrides(config, args)
        assert config.default_agent == original_agent
        assert config.max_iterations == original_iter

    def test_none_values_not_applied(self):
        config = AppConfig()
        original_iter = config.max_iterations
        args = Namespace(agent_cls=None, max_iterations=None, max_budget_per_task=None)
        apply_additional_overrides(config, args)
        assert config.max_iterations == original_iter


# ── apply_llm_config_override ───────────────────────────────────────


class TestApplyLlmConfigOverride:
    def test_no_config_no_change(self):
        config = AppConfig()
        args = Namespace(llm_config=None, config_file='settings.json')
        apply_llm_config_override(config, args)
        # No changes should occur

    def test_config_from_loaded(self):
        config = AppConfig()
        llm = LLMConfig(model='gpt-4')
        config.llms['custom'] = llm
        args = Namespace(llm_config='custom', config_file='settings.json')
        apply_llm_config_override(config, args)
        assert config.get_llm_config().model == 'gpt-4'

    def test_missing_config_raises(self, tmp_path):
        config = AppConfig()
        args = Namespace(
            llm_config='nonexistent', config_file=str(tmp_path / 'nonexistent.json')
        )
        with patch(
            'backend.core.config.cli_config.get_canonical_settings_path',
            return_value=str(tmp_path / 'settings.json'),
        ):
            with pytest.raises(ValueError, match='Cannot find'):
                apply_llm_config_override(config, args)

    def test_config_from_canonical_fallback(self, tmp_path):
        """Fallback reads LLM keys from canonical app-root settings.json."""
        main_config = tmp_path / 'main.json'
        main_config.write_text('{"agent_name": "test"}')

        canonical = tmp_path / 'settings.json'
        canonical.write_text('{"llm_model": "gpt-4-user"}')

        with patch(
            'backend.core.config.cli_config.get_canonical_settings_path',
            return_value=str(canonical),
        ):
            config = AppConfig()
            args = Namespace(llm_config='custom', config_file=str(main_config))
            apply_llm_config_override(config, args)
            assert config.get_llm_config().model == 'gpt-4-user'
