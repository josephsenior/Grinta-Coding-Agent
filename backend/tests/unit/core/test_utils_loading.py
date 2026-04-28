"""Tests for backend.core.config.config_loader — primary config loading entry points."""

from __future__ import annotations

import json
import os
from contextlib import contextmanager
from typing import Any, cast
from unittest.mock import MagicMock, patch

import pytest
from pydantic import SecretStr, ValidationError

from backend.core.config.agent_config import AgentConfig
from backend.core.config.api_key_manager import api_key_manager
from backend.core.config.app_config import AppConfig
from backend.core.config.compactor_config import AutoCompactorConfig
from backend.core.config.llm_config import LLMConfig
from backend.core.config.config_loader import (
    ConfigLoadSummary,
    _to_posix_workspace_path,
    finalize_config,
    get_agent_config_arg,
    get_compactor_config_arg,
    get_or_create_jwt_secret,
    load_app_config,
    load_from_json,
    parse_arguments,
    register_custom_agents,
    setup_config_from_args,
)

# ── ConfigLoadSummary ──────────────────────────────────────────────────


class TestConfigLoadSummary:
    def test_record_and_emit(self):
        summary = ConfigLoadSummary('test.toml')
        summary.record('core', 'invalid', 'bad value')
        summary.record_missing('agent', 'section missing')

        with patch('backend.core.logger.app_logger.warning') as mock_warn:
            summary.emit()
            mock_warn.assert_called_once()
            # args[0] is fmt, args[1] is file, args[2] is issues
            issues_str = mock_warn.call_args[0][2]
            assert '[agent] missing: section missing' in issues_str
            assert '[core] invalid: bad value' in issues_str

    def test_has_fatal_issues(self):
        summary = ConfigLoadSummary('test.toml')
        assert not summary.has_fatal_issues()
        summary.record('core', 'invalid', 'error')
        assert summary.has_fatal_issues()
        assert 'core: invalid: error' in summary.format_fatal_issues()

    def test_record_truncates_detail(self):
        summary = ConfigLoadSummary('test.toml')
        long_detail = 'a' * 300
        summary.record('section', 'reason', long_detail)
        assert len(summary._issues[0].detail) == 240
        assert summary._issues[0].detail.endswith('...')

    def test_emit_empty(self):
        summary = ConfigLoadSummary('test.toml')
        with patch('backend.core.logger.app_logger.warning') as mock_warn:
            summary.emit()
            mock_warn.assert_not_called()


# ── Path Helpers ──────────────────────────────────────────────────────


class TestPathHelpers:
    def test_to_posix_workspace_path(self):
        assert _to_posix_workspace_path('C:\\Users\\test') == '/Users/test'
        assert _to_posix_workspace_path('relative/path') == '/relative/path'
        assert _to_posix_workspace_path('/already/posix') == '/already/posix'
        assert _to_posix_workspace_path('') == ''
        assert _to_posix_workspace_path('') is not None

    def test_to_posix_with_double_slashes(self):
        assert _to_posix_workspace_path('path//with///slashes') == '/path/with/slashes'


# ── JWT Secret ────────────────────────────────────────────────────────


class TestJwtSecret:
    def test_get_existing_secret(self):
        mock_store = MagicMock()
        mock_store.read.return_value = 'existing_secret'
        assert get_or_create_jwt_secret(mock_store) == 'existing_secret'

    def test_create_new_secret(self):
        mock_store = MagicMock()
        mock_store.read.side_effect = FileNotFoundError()
        secret = get_or_create_jwt_secret(mock_store)
        assert len(secret) == 32  # uuid4().hex
        mock_store.write.assert_called_once()


# ── Finalization ──────────────────────────────────────────────────────


class TestFinalization:
    def test_finalize_config(self, tmp_path):
        cfg = AppConfig()
        cfg.cache_dir = str(tmp_path / 'cache')
        cfg.llms = {'default': MagicMock()}
        cfg.llms['default'].log_completions_folder = 'logs'

        with patch(
            'backend.core.config.config_loader.get_file_store'
        ) as mock_get_store:
            with patch('pathlib.Path.mkdir') as mock_mkdir:
                mock_store = MagicMock()
                mock_get_store.return_value = mock_store
                mock_store.read.return_value = 'secret'

                finalize_config(cfg)

                # assert os.path.exists(cfg.cache_dir) # Replaced by mock
                assert mock_mkdir.called
                assert os.path.isabs(cfg.llms['default'].log_completions_folder)
                assert cast(Any, cfg.jwt_secret).get_secret_value() == 'secret'

    def test_finalize_config_binds_auto_compactor_to_active_llm(self, tmp_path):
        cfg = AppConfig()
        cfg.cache_dir = str(tmp_path / 'cache')
        cfg.get_llm_config().model = 'openai/gpt-4.1'

        with (
            patch('backend.core.config.config_loader.get_file_store') as mock_get_store,
            patch('pathlib.Path.mkdir'),
        ):
            mock_store = MagicMock()
            mock_get_store.return_value = mock_store
            mock_store.read.return_value = 'secret'

            finalize_config(cfg)

        compactor_cfg = cfg.get_agent_config(cfg.default_agent).compactor_config
        assert isinstance(compactor_cfg, AutoCompactorConfig)
        assert compactor_cfg.llm_config.model == 'openai/gpt-4.1'  # type: ignore

    def test_finalize_config_loads_bundled_mcp_servers(self, tmp_path):
        cfg = AppConfig()
        cfg.cache_dir = str(tmp_path / 'cache')

        with (
            patch('backend.core.config.config_loader.get_file_store') as mock_get_store,
            patch('pathlib.Path.mkdir'),
            patch(
                'backend.core.config.mcp_config.load_bundled_mcp_server_configs',
                return_value=[],
            ),
        ):
            mock_store = MagicMock()
            mock_get_store.return_value = mock_store
            mock_store.read.return_value = 'secret'

            finalize_config(cfg)

        # Native browser follows active agent flags; bundled MCPs are always extended
        assert cfg.enable_browser is bool(
            cfg.get_agent_config(cfg.default_agent).enable_browsing
            and cfg.get_agent_config(cfg.default_agent).enable_native_browser
        )

    def test_finalize_config_creates_missing_auto_compactor(self, tmp_path):
        cfg = AppConfig()
        cfg.cache_dir = str(tmp_path / 'cache')
        cfg.get_agent_config(cfg.default_agent).compactor_config = None
        cfg.get_llm_config().model = 'openai/gpt-4.1'

        with (
            patch('backend.core.config.config_loader.get_file_store') as mock_get_store,
            patch('pathlib.Path.mkdir'),
        ):
            mock_store = MagicMock()
            mock_get_store.return_value = mock_store
            mock_store.read.return_value = 'secret'

            finalize_config(cfg)

        compactor_cfg = cfg.get_agent_config(cfg.default_agent).compactor_config
        assert isinstance(compactor_cfg, AutoCompactorConfig)
        assert compactor_cfg.llm_config is not None
        assert compactor_cfg.llm_config.model == 'openai/gpt-4.1'


# ── Named Group Loaders ───────────────────────────────────────────────


class TestNamedGroupLoaders:
    def test_get_agent_config_arg_success(self, tmp_path):
        json_file = tmp_path / 'settings.json'

        with patch('backend.core.config.config_loader._load_json_config') as mock_load:
            mock_load.return_value = {'agent': {'my_agent': {'name': 'custom_name'}}}
            config = get_agent_config_arg('agent.my_agent', str(json_file))
            assert isinstance(config, AgentConfig)
            assert config.name == 'custom_name'

    def test_get_agent_config_arg_missing(self, tmp_path):
        with patch(
            'backend.core.config.config_loader._load_json_config', return_value={}
        ):
            assert get_agent_config_arg('nonexistent') is None

    def test_get_agent_config_arg_returns_none_when_json_missing(self):
        with patch(
            'backend.core.config.config_loader._load_json_config', return_value=None
        ):
            assert get_agent_config_arg('agent.anything') is None

    def test_get_compactor_config_arg_success(self, tmp_path):
        json_file = tmp_path / 'settings.json'
        # Mocking to avoid complex dependencies
        with patch('backend.core.config.config_loader._load_json_config') as mock_load:
            mock_load.return_value = {
                'compactor_type': 'recent',
                'compactor_max_events': 10,
            }
            with patch(
                'backend.core.config.compactor_config.create_compactor_config'
            ) as mock_create:
                mock_cfg = MagicMock()
                mock_create.return_value = mock_cfg
                result = get_compactor_config_arg('my_compactor', str(json_file))
                assert result is mock_cfg

    def test_get_compactor_config_arg_missing_type(self, tmp_path):
        with patch('backend.core.config.config_loader._load_json_config') as mock_load:
            mock_load.return_value = {'compactor_type': None}
            assert get_compactor_config_arg('bad') is None

    def test_get_compactor_config_arg_returns_none_when_json_missing(self):
        with patch(
            'backend.core.config.config_loader._load_json_config', return_value=None
        ):
            assert get_compactor_config_arg('missing') is None

    def test_get_compactor_config_arg_passes_keep_first(self):
        with patch('backend.core.config.config_loader._load_json_config') as mock_load:
            mock_load.return_value = {
                'compactor_type': 'recent',
                'compactor_keep_first': 3,
            }
            with patch(
                'backend.core.config.compactor_config.create_compactor_config'
            ) as mock_create:
                mock_cfg = MagicMock()
                mock_create.return_value = mock_cfg

                result = get_compactor_config_arg('keep_first_cfg')

        assert result is mock_cfg
        mock_create.assert_called_once_with('recent', {'type': 'recent', 'keep_first': 3})


# ── Agent Registration ────────────────────────────────────────────────


class TestAgentRegistration:
    def test_register_custom_agents(self):
        cfg = AppConfig()
        mock_agent_cfg = MagicMock()
        mock_agent_cfg.classpath = 'some.module.Class'
        cfg.agents = {'custom': mock_agent_cfg}

        with patch('backend.core.config.config_loader.get_impl') as mock_get_impl:
            mock_cls = MagicMock()
            mock_get_impl.return_value = mock_cls
            from backend.orchestration.agent import Agent

            with patch.object(Agent, 'register') as mock_register:
                register_custom_agents(cfg)
                mock_register.assert_called_with('custom', mock_cls)


# ── Main Entry Points ─────────────────────────────────────────────────


class TestMainEntryPoints:
    @patch('backend.core.config.config_loader.rebuild_config_models')
    @patch('backend.core.config.config_loader.load_from_json')
    @patch('backend.core.config.config_loader.load_from_env')
    @patch('backend.core.config.config_loader.finalize_config')
    @patch('backend.core.config.config_loader.export_llm_api_keys')
    @patch('backend.core.config.config_loader.register_custom_agents')
    def test_load_app_config_calls(self, *mocks):
        # This test only verifies that the other functions are called
        load_app_config(set_logging_levels=True)
        for m in mocks:
            assert m.called

    def test_load_app_config_execution(self, tmp_path):
        # This test actually executes the function (with minimal mocking)
        with patch('backend.core.config.config_loader.rebuild_config_models'):
            with patch('backend.core.config.config_loader.load_from_json'):
                with patch('backend.core.config.config_loader.load_from_env'):
                    with patch('backend.core.config.config_loader.finalize_config'):
                        with patch(
                            'backend.core.config.config_loader.export_llm_api_keys'
                        ):
                            with patch(
                                'backend.core.config.config_loader.register_custom_agents'
                            ):
                                # This will execute the body of load_app_config
                                load_app_config(set_logging_levels=True)

    def test_load_app_config_uses_repo_anchored_settings_path(self, tmp_path):
        settings_root = tmp_path / 'repo-root'
        settings_root.mkdir()
        expected_settings = settings_root / 'settings.json'

        with patch(
            'backend.core.config.config_loader.get_canonical_settings_path',
            return_value=str(expected_settings),
        ):
            with patch('backend.core.config.config_loader.rebuild_config_models'):
                with patch(
                    'backend.core.config.config_loader.load_from_json'
                ) as mock_json:
                    with patch('backend.core.config.config_loader.load_from_env'):
                        with patch('backend.core.config.config_loader.finalize_config'):
                            with patch(
                                'backend.core.config.config_loader.export_llm_api_keys'
                            ):
                                with patch(
                                    'backend.core.config.config_loader.register_custom_agents'
                                ):
                                    load_app_config(set_logging_levels=False)

        mock_json.assert_called_once()
        assert mock_json.call_args[0][1] == str(expected_settings)

    def test_setup_config_from_args_execution(self):
        args = MagicMock()
        args.config_file = 'settings.json'
        with patch('backend.core.config.config_loader.load_app_config') as mock_load:
            with patch('backend.core.config.config_loader.apply_llm_config_override'):
                with patch(
                    'backend.core.config.config_loader.apply_additional_overrides'
                ):
                    setup_config_from_args(args)
                    mock_load.assert_called_with(config_file='settings.json')

    def test_load_app_config_warns_on_external_file_and_syncs_explicit_api_key(self):
        original_model_validate = LLMConfig.model_validate

        class _FakeAPIKeyManager:
            def __init__(self) -> None:
                self.suppress_env_export = True
                self.set_api_key_calls: list[tuple[str | None, SecretStr | None]] = []
                self.set_environment_calls: list[
                    tuple[str | None, SecretStr | None]
                ] = []

            @contextmanager
            def suppress_env_export_context(self):
                yield

            def set_api_key(self, model: str | None, api_key: SecretStr) -> None:
                self.set_api_key_calls.append((model, api_key))

            def set_environment_variables(
                self, model: str | None, api_key: SecretStr | None
            ) -> None:
                self.set_environment_calls.append((model, api_key))

            def extract_provider(self, model: str) -> str:
                return 'groq'

            def get_provider_key_from_env(self, provider: str) -> str | None:
                return None

        def _seed_env(cfg: AppConfig, _env: dict[str, str]) -> None:
            cfg.set_llm_config(
                LLMConfig.model_validate(
                    {
                        'model': 'groq/meta-llama/llama-4-scout',
                        'api_key': 'x' * 32,
                    }
                )
            )

        def _validate_llm(payload, *args, **kwargs):
            api_key = payload.get('api_key') if isinstance(payload, dict) else None
            if isinstance(payload, dict) and api_key is None:
                llm_cfg = LLMConfig()
                for key, value in payload.items():
                    object.__setattr__(llm_cfg, key, value)
                object.__setattr__(llm_cfg, 'api_key', None)
                return llm_cfg
            if isinstance(payload, dict) and hasattr(api_key, 'get_secret_value'):
                payload = {**payload, 'api_key': api_key.get_secret_value()}
            return original_model_validate(payload, *args, **kwargs)

        fake_manager = _FakeAPIKeyManager()

        with (
            patch('backend.core.config.config_loader.get_canonical_settings_path', return_value='canonical.json'),
            patch('backend.core.config.config_loader.rebuild_config_models'),
            patch('backend.core.config.config_loader.load_from_env', side_effect=_seed_env),
            patch('backend.core.config.config_loader.load_from_json'),
            patch('backend.core.config.config_loader.finalize_config'),
            patch('backend.core.config.config_loader.export_llm_api_keys'),
            patch('backend.core.config.config_loader.register_custom_agents'),
            patch('backend.core.config.api_key_manager.api_key_manager', fake_manager),
            patch('backend.core.config.llm_config.api_key_manager', fake_manager),
            patch('backend.core.config.config_loader.logger.app_logger.warning') as mock_warn,
            patch('backend.core.config.llm_config.LLMConfig.model_validate', side_effect=_validate_llm),
        ):
            cfg = load_app_config(set_logging_levels=False, config_file='custom.json')

        llm_cfg = cfg.get_llm_config()
        mock_warn.assert_any_call(
            'Ignoring external config_file=%s; using canonical settings=%s',
            'custom.json',
            'canonical.json',
        )
        assert fake_manager.set_api_key_calls == [(llm_cfg.model, llm_cfg.api_key)]
        assert fake_manager.set_environment_calls == [
            (llm_cfg.model, llm_cfg.api_key)
        ]

    def test_load_app_config_backfills_api_key_from_provider_env(self):
        original_model_validate = LLMConfig.model_validate

        class _FakeAPIKeyManager:
            def __init__(self) -> None:
                self.suppress_env_export = True
                self.set_api_key_calls: list[tuple[str | None, SecretStr | None]] = []
                self.set_environment_calls: list[
                    tuple[str | None, SecretStr | None]
                ] = []

            @contextmanager
            def suppress_env_export_context(self):
                yield

            def set_api_key(self, model: str | None, api_key: SecretStr) -> None:
                self.set_api_key_calls.append((model, api_key))

            def set_environment_variables(
                self, model: str | None, api_key: SecretStr | None
            ) -> None:
                self.set_environment_calls.append((model, api_key))

            def extract_provider(self, model: str) -> str:
                return 'groq'

            def get_provider_key_from_env(self, provider: str) -> str | None:
                return 'env-secret-long-enough-123456'

        def _seed_env(cfg: AppConfig, _env: dict[str, str]) -> None:
            llm_cfg = LLMConfig()
            object.__setattr__(llm_cfg, 'model', 'groq/meta-llama/llama-4-scout')
            object.__setattr__(llm_cfg, 'api_key', None)
            cfg.set_llm_config(llm_cfg)

        def _validate_llm(payload, *args, **kwargs):
            api_key = payload.get('api_key') if isinstance(payload, dict) else None
            if isinstance(payload, dict) and hasattr(api_key, 'get_secret_value'):
                payload = {**payload, 'api_key': api_key.get_secret_value()}
            return original_model_validate(payload, *args, **kwargs)

        fake_manager = _FakeAPIKeyManager()

        with (
            patch('backend.core.config.config_loader.rebuild_config_models'),
            patch('backend.core.config.config_loader.load_from_env', side_effect=_seed_env),
            patch('backend.core.config.config_loader.load_from_json'),
            patch('backend.core.config.config_loader.finalize_config'),
            patch('backend.core.config.config_loader.export_llm_api_keys'),
            patch('backend.core.config.config_loader.register_custom_agents'),
            patch('backend.core.config.api_key_manager.api_key_manager', fake_manager),
            patch('backend.core.config.llm_config.api_key_manager', fake_manager),
            patch('backend.core.config.llm_config.LLMConfig.model_validate', side_effect=_validate_llm),
        ):
            cfg = load_app_config(set_logging_levels=False)

        llm_cfg = cfg.get_llm_config()
        assert llm_cfg.api_key is not None
        assert llm_cfg.api_key.get_secret_value() == 'env-secret-long-enough-123456'
        assert fake_manager.set_api_key_calls == [(llm_cfg.model, llm_cfg.api_key)]
        assert fake_manager.set_environment_calls == [
            (llm_cfg.model, llm_cfg.api_key)
        ]


# ── Config load (load_from_json) ──────────────────────────────────────


class TestLoadFromJson:
    def test_load_from_json_success(self, tmp_path):
        json_file = tmp_path / 'settings.json'
        json_file.write_text('{"mcp_host": "custom-host:9999"}')
        cfg = AppConfig()
        load_from_json(cfg, str(json_file))
        assert cfg.mcp_host == 'custom-host:9999'

    def test_load_from_json_requires_provider_for_unprefixed_model(self, tmp_path):
        json_file = tmp_path / 'settings.json'
        json_file.write_text('{"llm_model": "gpt-4o"}')
        cfg = AppConfig()
        with patch(
            'backend.core.config.config_loader.logger.app_logger.warning'
        ) as mock_warn:
            load_from_json(cfg, str(json_file))
        mock_warn.assert_called()
        assert cfg.get_llm_config().model is None

    def test_load_from_json_applies_explicit_provider(self, tmp_path):
        json_file = tmp_path / 'settings.json'
        json_file.write_text(
            '{"llm_model": "meta-llama/llama-4-scout", "llm_provider": "groq"}'
        )
        cfg = AppConfig()
        load_from_json(cfg, str(json_file))
        assert cfg.get_llm_config().model == 'groq/meta-llama/llama-4-scout'

    def test_load_from_json_blank_model_clears_existing_model(self, tmp_path):
        json_file = tmp_path / 'settings.json'
        json_file.write_text('{"llm_model": "   ", "llm_provider": "openai"}')
        cfg = AppConfig()
        cfg.set_llm_config(
            LLMConfig.model_validate({'model': 'openai/gpt-4.1', 'api_key': 'seed'})
        )

        load_from_json(cfg, str(json_file))

        assert cfg.get_llm_config().model is None

    def test_load_from_json_native_google_ignores_base_url(self, tmp_path):
        json_file = tmp_path / 'settings.json'
        json_file.write_text(
            json.dumps(
                {
                    'llm_model': 'google/gemini-2.5-flash',
                    'llm_base_url': 'https://proxy.example/v1',
                }
            )
        )
        cfg = AppConfig()

        load_from_json(cfg, str(json_file))

        llm_cfg = cfg.get_llm_config()
        assert llm_cfg.model == 'google/gemini-2.5-flash'
        assert not llm_cfg.base_url

    def test_load_from_json_preserves_explicit_base_url_for_proxy_provider(
        self, tmp_path
    ) -> None:
        json_file = tmp_path / 'settings.json'
        json_file.write_text(
            json.dumps(
                {
                    'llm_model': 'meta-llama/llama-4-scout',
                    'llm_provider': 'groq',
                    'llm_base_url': 'https://proxy.example/v1',
                }
            )
        )
        cfg = AppConfig()

        load_from_json(cfg, str(json_file))

        assert cfg.get_llm_config().base_url == 'https://proxy.example/v1'

    def test_load_from_json_sets_provider_default_base_url_for_lightning(
        self, tmp_path
    ) -> None:
        from backend.inference.provider_resolver import _PROVIDER_DEFAULT_URLS

        json_file = tmp_path / 'settings.json'
        json_file.write_text(
            json.dumps(
                {
                    'llm_model': 'meta-llama/llama-4-scout',
                    'llm_provider': 'lightning',
                }
            )
        )
        cfg = AppConfig()

        load_from_json(cfg, str(json_file))

        llm_cfg = cfg.get_llm_config()
        assert llm_cfg.model == 'openai/meta-llama/llama-4-scout'
        assert llm_cfg.base_url == _PROVIDER_DEFAULT_URLS['lightning']

    def test_load_from_json_llm_api_key_warns_on_literal_uses_env(
        self, tmp_path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        json_file = tmp_path / 'settings.json'
        json_file.write_text(
            json.dumps(
                {
                    'llm_model': 'meta-llama/llama-4-scout',
                    'llm_provider': 'groq',
                    'llm_api_key': 'key-from-settings-json',
                }
            )
        )
        cfg = AppConfig()
        monkeypatch.setenv('LLM_API_KEY', 'key-from-env')
        with patch('backend.core.config.config_loader.logger.app_logger.warning') as w:
            load_from_json(cfg, str(json_file))
        w.assert_called()
        api_key = cfg.get_llm_config().api_key
        assert api_key is not None
        assert api_key.get_secret_value() == 'key-from-env'

    def test_load_from_json_llm_api_key_literal_ignored_without_env(
        self, tmp_path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        json_file = tmp_path / 'settings.json'
        json_file.write_text(
            json.dumps(
                {
                    'llm_model': 'meta-llama/llama-4-scout',
                    'llm_provider': 'groq',
                    'llm_api_key': 'only-in-json',
                }
            )
        )
        cfg = AppConfig()
        monkeypatch.delenv('LLM_API_KEY', raising=False)
        with api_key_manager.suppress_env_export_context():
            load_from_json(cfg, str(json_file))
        assert cfg.get_llm_config().api_key is None

    def test_load_from_json_llm_api_key_placeholder_uses_env(
        self, tmp_path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from backend.core.constants import LLM_API_KEY_SETTINGS_PLACEHOLDER

        json_file = tmp_path / 'settings.json'
        json_file.write_text(
            json.dumps(
                {
                    'llm_model': 'meta-llama/llama-4-scout',
                    'llm_provider': 'groq',
                    'llm_api_key': LLM_API_KEY_SETTINGS_PLACEHOLDER,
                }
            )
        )
        cfg = AppConfig()
        monkeypatch.setenv('LLM_API_KEY', 'from-dotenv')
        load_from_json(cfg, str(json_file))
        api_key = cfg.get_llm_config().api_key
        assert api_key is not None
        assert api_key.get_secret_value() == 'from-dotenv'

    def test_load_from_json_file_not_found(self):
        cfg = AppConfig()
        # Should return silently
        load_from_json(cfg, 'nonexistent.json')

    def test_load_from_json_decode_error(self, tmp_path):
        json_file = tmp_path / 'bad.json'
        json_file.write_text('invalid } json { here')
        cfg = AppConfig()
        with patch('backend.core.logger.app_logger.warning') as mock_warn:
            load_from_json(cfg, str(json_file))
            mock_warn.assert_called()

    def test_load_from_json_strict_mode_fail(self, tmp_path):
        json_file = tmp_path / 'bad.json'
        json_file.write_text('invalid } json { here')
        with patch.dict(os.environ, {'APP_STRICT_CONFIG': 'true'}):
            with pytest.raises(ValueError, match='Invalid JSON'):
                load_from_json(AppConfig(), str(json_file))

    def test_load_from_json_requires_provider_raises_in_strict_mode(self, tmp_path):
        json_file = tmp_path / 'settings.json'
        json_file.write_text('{"llm_model": "gpt-4o"}')

        with patch.dict(os.environ, {'APP_STRICT_CONFIG': 'true'}):
            with pytest.raises(ValueError, match='llm_provider is required'):
                load_from_json(AppConfig(), str(json_file))

    def test_load_from_json_strict_mode_fatal_issue(self, tmp_path):
        json_file = tmp_path / 'settings.json'
        json_file.write_text('{}')
        with patch.dict(os.environ, {'APP_STRICT_CONFIG': 'true'}):
            with patch.object(ConfigLoadSummary, 'has_fatal_issues', return_value=True):
                with patch.object(
                    ConfigLoadSummary,
                    'format_fatal_issues',
                    return_value='core: invalid: bad value',
                ):
                    with pytest.raises(ValueError, match='config load issues'):
                        load_from_json(AppConfig(), str(json_file))

    def test_load_from_json_sets_project_root_and_merges_mcp_servers(
        self, tmp_path
    ) -> None:
        from backend.core.config.mcp_config import MCPServerConfig

        project_root = tmp_path / 'workspace'
        json_file = tmp_path / 'settings.json'
        json_file.write_text(
            json.dumps(
                {
                    'project_root': str(project_root),
                    'mcp_config': {
                        'servers': [
                            {'name': 'existing', 'type': 'stdio', 'command': 'python'},
                            {'name': 'remote', 'type': 'shttp', 'url': 'https://example.com'},
                            'not-a-dict',
                            {'name': 'broken', 'type': 'stdio'},
                        ]
                    },
                }
            )
        )
        cfg = AppConfig()
        cfg.mcp.servers = [
            MCPServerConfig(name='existing', type='stdio', command='python')
        ]

        with patch('backend.core.config.config_loader.logger.app_logger.debug') as mock_debug:
            load_from_json(cfg, str(json_file))

        assert cfg.project_root == str(project_root)
        assert [server.name for server in cfg.mcp.servers] == ['existing', 'remote']
        assert cfg.mcp.enabled is True
        mock_debug.assert_called()

    def test_load_from_json_applies_valid_agent_overrides_and_skips_invalid(
        self, tmp_path
    ) -> None:
        json_file = tmp_path / 'settings.json'
        json_file.write_text(
            json.dumps(
                {
                    'agent': {
                        'custom': {'name': 'customized'},
                        'skip_me': 'not-a-dict',
                        'ignore_unknown': {'unknown_field': True},
                        'broken': {'memory_max_threads': 'invalid'},
                    }
                }
            )
        )
        cfg = AppConfig()

        with patch('backend.core.config.config_loader.logger.app_logger.warning') as mock_warn:
            load_from_json(cfg, str(json_file))

        assert cfg.agents['custom'].name == 'customized'
        assert 'ignore_unknown' not in cfg.agents
        mock_warn.assert_called()


# ── Compactor Loader Extra ───────────────────────────────────────────


class TestCompactorLoaderExtra:
    def test_get_compactor_config_missing_section(self, tmp_path):
        with patch(
            'backend.core.config.config_loader._load_json_config', return_value={}
        ):
            assert get_compactor_config_arg('my_compactor') is None

    def test_get_compactor_config_arg_validation_error(self, tmp_path):
        with patch(
            'backend.core.config.config_loader._load_json_config',
            return_value={'compactor_type': 'recent'},
        ):
            with patch(
                'backend.core.config.compactor_config.create_compactor_config',
                side_effect=ValidationError.from_exception_data('test', []),
            ):
                assert get_compactor_config_arg('my_compactor') is None

    def test_process_llm_compactor_success(self):
        from backend.core.config.config_loader import _process_llm_compactor

        compactor_data = {'llm_config': 'my_llm'}
        with patch('backend.core.config.config_loader.get_llm_config_arg') as mock_get:
            mock_llm = MagicMock()
            mock_get.return_value = mock_llm
            result = _process_llm_compactor(compactor_data, 'arg', 'file.toml')
            assert result is not None
            assert result['llm_config'] is mock_llm

    def test_process_llm_compactor_fail(self):
        from backend.core.config.config_loader import _process_llm_compactor

        compactor_data = {'llm_config': 'my_llm'}
        with patch(
            'backend.core.config.config_loader.get_llm_config_arg', return_value=None
        ):
            assert _process_llm_compactor(compactor_data, 'arg', 'file.toml') is None

    def test_process_llm_compactor_without_llm_config(self):
        from backend.core.config.config_loader import _process_llm_compactor

        assert _process_llm_compactor({}, 'arg', 'file.toml') is None


# ── Agent Registration Extra ──────────────────────────────────────────


class TestAgentRegistrationExtra:
    def test_register_custom_agents_failure_handled(self):
        cfg = AppConfig()
        mock_agent_cfg = MagicMock()
        mock_agent_cfg.classpath = 'bad.Path'
        cfg.agents = {'bad': mock_agent_cfg}

        with patch(
            'backend.core.config.config_loader.get_impl',
            side_effect=Exception('import fail'),
        ):
            # Should not raise
            register_custom_agents(cfg)

    def test_register_custom_agents_no_classpath(self):
        cfg = AppConfig()
        cfg.agents = {'no_cp': MagicMock(spec=[])}  # No classpath attribute
        # Should just skip
        register_custom_agents(cfg)


class TestCoverageGapsV2:
    def test_format_fatal_issues_empty(self):
        summary = ConfigLoadSummary('test.toml')
        assert summary.format_fatal_issues() == ''

    def test_format_fatal_issues_loop(self):
        summary = ConfigLoadSummary('test.toml')
        summary.record('core', 'invalid', 'err1')
        summary.record('agent', 'invalid', 'err2')
        formatted = summary.format_fatal_issues()
        assert 'core: invalid: err1' in formatted
        assert 'agent: invalid: err2' in formatted

    def test_get_agent_config_arg_debug_log(self, tmp_path):
        with patch(
            'backend.core.config.config_loader._load_json_config',
            return_value={'agent': {}},
        ):
            with patch('backend.core.logger.app_logger.debug') as mock_debug:
                assert get_agent_config_arg('my_agent') is None
                mock_debug.assert_any_call(
                    'Loading from toml failed for %s', 'my_agent'
                )

    def test_get_compactor_config_arg_logs(self, tmp_path):
        # Test success log (roughly line 315)
        with patch(
            'backend.core.config.config_loader._load_json_config',
            return_value={'compactor_type': 'recent'},
        ):
            with patch(
                'backend.core.config.compactor_config.create_compactor_config'
            ) as mock_create:
                mock_cfg = MagicMock()
                mock_create.return_value = mock_cfg
                with patch('backend.core.logger.app_logger.info') as mock_info:
                    get_compactor_config_arg('c1')
                    mock_info.assert_called()

        # Test error log missing type (roughly line 330)
        with patch(
            'backend.core.config.config_loader._load_json_config',
            return_value={'compactor_type': None},
        ):
            with patch('backend.core.logger.app_logger.error') as mock_error:
                get_compactor_config_arg('c2')
                mock_error.assert_called_with(
                    'Missing "type" field in [compactor.%s] section of %s',
                    'c2',
                    'settings.json',
                )

        # Test error log for failed LLM load (roughly line 351/304)
        with patch(
            'backend.core.config.config_loader._load_json_config',
            return_value={'compactor_type': 'llm', 'compactor_llm_config': 'missing'},
        ):
            with patch(
                'backend.core.config.config_loader.get_llm_config_arg',
                return_value=None,
            ):
                with patch('backend.core.logger.app_logger.error') as mock_error:
                    get_compactor_config_arg('c3')
                    mock_error.assert_any_call(
                        "Failed to load required LLM config '%s' for compactor '%s'.",
                        'missing',
                        'c3',
                    )

    def test_parse_arguments_version(self):
        with patch('backend.core.config.arg_utils.get_headless_parser') as mock_get:
            mock_parser = MagicMock()
            mock_get.return_value = mock_parser
            mock_parser.parse_args.return_value = MagicMock(version=True)
            with pytest.raises(SystemExit) as exc:
                parse_arguments()
            assert exc.value.code == 0

    def test_parse_arguments_no_version(self):
        with patch('backend.core.config.arg_utils.get_headless_parser') as mock_get:
            mock_parser = MagicMock()
            mock_get.return_value = mock_parser
            mock_parser.parse_args.return_value = MagicMock(version=False)
            args = parse_arguments()
            assert args.version is False
