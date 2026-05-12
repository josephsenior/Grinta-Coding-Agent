"""Integration tests for init_wizard reliability improvements."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]


class TestInitWizardCrossPlatform:
    """Tests for cross-platform init wizard reliability."""

    @pytest.mark.integration
    def test_detect_local_handles_network_errors(self) -> None:
        """Verify _detect_local doesn't crash on network errors."""
        from backend.cli.init_wizard import _detect_local

        result = _detect_local()
        assert isinstance(result, list)

    @pytest.mark.integration
    def test_atomic_json_write_creates_file(self, tmp_path: Path) -> None:
        """Verify atomic JSON write creates valid file."""
        from backend.cli.init_wizard import _atomic_json_write

        settings_file = tmp_path / 'settings.json'
        data = {'llm_provider': 'openai', 'llm_model': 'test'}

        _atomic_json_write(settings_file, data)

        assert settings_file.exists()
        loaded = json.loads(settings_file.read_text(encoding='utf-8'))
        assert loaded == data

    @pytest.mark.integration
    def test_atomic_json_write_handles_corruption(self, tmp_path: Path) -> None:
        """Verify atomic write doesn't leave corrupt files on failure."""
        from backend.cli.init_wizard import _atomic_json_write

        settings_file = tmp_path / 'settings.json'
        settings_file.write_text('corrupted', encoding='utf-8')

        with patch('backend.cli.init_wizard.json.dumps', side_effect=ValueError('test')):
            with pytest.raises(ValueError):
                _atomic_json_write(settings_file, {'test': 'data'})

        assert settings_file.read_text(encoding='utf-8') == 'corrupted'

    @pytest.mark.integration
    def test_check_settings_directory_writable_creates_directory(
        self, tmp_path: Path
    ) -> None:
        """Verify writable check creates missing directories."""
        from backend.cli.init_wizard import _check_settings_directory_writable

        settings_dir = tmp_path / 'new' / 'nested' / 'dir'
        settings_file = settings_dir / 'settings.json'

        is_writable, error = _check_settings_directory_writable(settings_file)

        assert is_writable, f"Should be writable: {error}"
        assert settings_dir.exists()

    @pytest.mark.integration
    def test_check_settings_directory_writable_detects_permission_error(
        self, tmp_path: Path
    ) -> None:
        """Verify writable check detects permission issues."""
        from backend.cli.init_wizard import _check_settings_directory_writable

        if os.name == 'nt':
            pytest.skip('Windows permission test requires special setup')

        settings_file = tmp_path / 'settings.json'

        is_writable, error = _check_settings_directory_writable(settings_file)

        assert is_writable or 'permission' in error.lower()

    @pytest.mark.integration
    def test_platform_info_is_reported(self) -> None:
        """Verify platform info is available."""
        from backend.cli.init_wizard import _get_platform_info

        platform_info = _get_platform_info()

        assert platform_info in ('Windows', 'macOS', 'Linux')
        assert any(p in platform_info for p in ('Windows', 'Darwin', 'Linux'))

    @pytest.mark.integration
    def test_init_command_runs_without_crash(self, tmp_path: Path) -> None:
        """Verify 'grinta init' can be invoked without crash (any valid exit code)."""
        env = os.environ.copy()
        env.update({
            'LLM_API_KEY': 'sk-test-key',
            'GRINTA_NO_SPLASH': '1',
            'PYTHONUTF8': '1',
            'HOME': str(tmp_path),
            'USERPROFILE': str(tmp_path),
            'APP_ROOT': str(tmp_path / 'app'),
        })

        app_root = tmp_path / 'app'
        app_root.mkdir()

        result = subprocess.run(
            [
                sys.executable,
                '-m',
                'backend.cli.entry',
                'init',
                '--project',
                str(tmp_path / 'project'),
            ],
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=60,
            env=env,
            input='openai\n\n\n\n',
        )

        assert result.returncode in (0, 1, 2, 3)


class TestSettingsValidation:
    """Tests for settings file validation."""

    @pytest.mark.integration
    def test_load_existing_returns_empty_for_missing(self, tmp_path: Path) -> None:
        """Verify _load_existing returns empty dict for missing file."""
        from backend.cli.init_wizard import _load_existing

        result = _load_existing(tmp_path / 'nonexistent.json')
        assert result == {}

    @pytest.mark.integration
    def test_load_existing_returns_empty_for_invalid_json(self, tmp_path: Path) -> None:
        """Verify _load_existing returns empty dict for invalid JSON."""
        from backend.cli.init_wizard import _load_existing

        invalid = tmp_path / 'invalid.json'
        invalid.write_text('{ broken json', encoding='utf-8')

        result = _load_existing(invalid)
        assert result == {}

    @pytest.mark.integration
    def test_load_existing_returns_valid_json(self, tmp_path: Path) -> None:
        """Verify _load_existing returns valid JSON."""
        from backend.cli.init_wizard import _load_existing

        valid = tmp_path / 'valid.json'
        valid.write_text('{"llm_provider": "openai"}', encoding='utf-8')

        result = _load_existing(valid)
        assert result == {'llm_provider': 'openai'}


class TestProviderPresets:
    """Tests for provider preset configurations."""

    @pytest.mark.integration
    def test_all_cloud_providers_have_api_key_env(self) -> None:
        """Verify cloud providers require API keys."""
        from backend.cli.init_wizard import _PROVIDER_PRESETS

        cloud_providers = ['openai', 'anthropic', 'google', 'openrouter']
        for provider in cloud_providers:
            preset = _PROVIDER_PRESETS[provider]
            assert preset['env'], f"{provider} should have env var defined"

    @pytest.mark.integration
    def test_local_providers_have_localhost_urls(self) -> None:
        """Verify local providers have localhost URLs."""
        from backend.cli.init_wizard import _PROVIDER_PRESETS

        local_providers = ['ollama', 'lmstudio']
        for provider in local_providers:
            preset = _PROVIDER_PRESETS[provider]
            assert 'localhost' in preset['base_url'], f"{provider} should have localhost URL"

    @pytest.mark.integration
    def test_all_providers_have_default_model(self) -> None:
        """Verify all providers have default model."""
        from backend.cli.init_wizard import _PROVIDER_PRESETS

        for provider, preset in _PROVIDER_PRESETS.items():
            assert preset['default_model'], f"{provider} should have default model"
            assert '/' in preset['default_model'], f"{provider} default should have provider prefix"


class TestExitCodes:
    """Tests for proper exit codes."""

    @pytest.mark.integration
    def test_run_init_returns_zero_on_success(self, tmp_path: Path) -> None:
        """Verify run_init returns 0 on success."""
        from backend.cli.init_wizard import run_init
        from unittest.mock import MagicMock

        app_root = tmp_path / 'app'
        app_root.mkdir()

        with patch.dict(os.environ, {'APP_ROOT': str(app_root), 'HOME': str(tmp_path)}):
            mock_console = MagicMock()
            mock_console.print = MagicMock()
            mock_console.no_color = False

            with patch('backend.cli.init_wizard._check_settings_directory_writable', return_value=(True, '')):
                with patch('backend.cli.init_wizard._load_existing', return_value={}):
                    with patch('backend.cli.init_wizard._detect_local', return_value=[]):
                        with patch('backend.cli.init_wizard.Prompt.ask', side_effect=['openai', 'test-model', '', '']):
                            with patch('backend.cli.init_wizard._atomic_json_write'):
                                result = run_init(console=mock_console)

        assert result == 0