"""Tests for backend.cli.onboarding.init_wizard."""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from rich.console import Console

from backend.cli.onboarding.init_wizard import (
    _collect_api_key,
    _confirm_overwrite_existing,
    _detect_local,
    _http_ok,
    _load_existing,
    _print_provider_table,
    _settings_path,
    run_init,
)


def _quiet_console() -> Console:
    return Console(quiet=True)


def _patch_settings_path(path: Path):
    return patch(
        'backend.cli.onboarding.init_wizard.get_canonical_settings_path',
        return_value=str(path),
    )


@pytest.fixture(autouse=True)
def _clear_llm_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv('LLM_API_KEY', raising=False)


# ---------------------------------------------------------------------------
# _http_ok
# ---------------------------------------------------------------------------


class TestHttpOk:
    def test_non_http_scheme_returns_false(self) -> None:
        assert _http_ok('ftp://example.com') is False
        assert _http_ok('file:///etc/passwd') is False
        assert _http_ok('/local/path') is False

    def test_successful_request_returns_true(self) -> None:
        fake_resp = MagicMock()
        fake_resp.status = 200
        fake_resp.__enter__ = lambda s: s
        fake_resp.__exit__ = MagicMock(return_value=False)
        with patch('urllib.request.urlopen', return_value=fake_resp):
            assert _http_ok('http://localhost:11434') is True

    def test_failed_request_returns_false(self) -> None:
        with patch('urllib.request.urlopen', side_effect=OSError('refused')):
            assert _http_ok('http://localhost:99999') is False


class TestDetectLocal:
    def test_none_detected(self) -> None:
        with patch(
            'backend.cli.onboarding.init_wizard.check_local_providers',
            return_value={'ollama': False, 'lm_studio': False, 'vllm': False},
        ):
            assert _detect_local() == []

    def test_ollama_detected(self) -> None:
        with patch(
            'backend.cli.onboarding.init_wizard.check_local_providers',
            return_value={'ollama': True, 'lm_studio': False, 'vllm': False},
        ):
            assert _detect_local() == ['ollama']

    def test_vllm_detected(self) -> None:
        with patch(
            'backend.cli.onboarding.init_wizard.check_local_providers',
            return_value={'ollama': False, 'lm_studio': False, 'vllm': True},
        ):
            assert _detect_local() == ['vllm']

    def test_multiple_detected(self) -> None:
        with patch(
            'backend.cli.onboarding.init_wizard.check_local_providers',
            return_value={'ollama': True, 'lm_studio': True, 'vllm': False},
        ):
            result = _detect_local()
            assert 'ollama' in result
            assert 'lm_studio' in result


class TestSettingsPath:
    def test_returns_settings_json(self, tmp_path: Path) -> None:
        expected = tmp_path / 'settings.json'
        with _patch_settings_path(expected):
            p = _settings_path(tmp_path)
        assert p == expected


class TestLoadExisting:
    def test_no_file(self, tmp_path: Path) -> None:
        result = _load_existing(tmp_path / 'settings.json')
        assert result == {}

    def test_valid_json(self, tmp_path: Path) -> None:
        f = tmp_path / 'settings.json'
        f.write_text(json.dumps({'llm_model': 'openai/gpt-4o'}), encoding='utf-8')
        result = _load_existing(f)
        assert result['llm_model'] == 'openai/gpt-4o'

    def test_invalid_json(self, tmp_path: Path) -> None:
        f = tmp_path / 'settings.json'
        f.write_text('{bad json', encoding='utf-8')
        result = _load_existing(f)
        assert result == {}


class TestConfirmOverwriteExisting:
    def test_confirm_yes(self) -> None:
        console = _quiet_console()
        with patch('rich.prompt.Confirm.ask', return_value=True):
            result = _confirm_overwrite_existing(
                console, {'llm_model': 'x', 'llm_provider': 'y'}
            )
        assert result is True

    def test_confirm_no(self) -> None:
        console = _quiet_console()
        with patch('rich.prompt.Confirm.ask', return_value=False):
            result = _confirm_overwrite_existing(
                console, {'llm_model': 'x', 'llm_provider': 'y'}
            )
        assert result is False


class TestPrintProviderTable:
    def test_runs_without_error(self) -> None:
        console = _quiet_console()
        # Should not raise
        _print_provider_table(console, ['ollama'])


class TestCollectApiKey:
    def test_no_env_var(self) -> None:
        preset = {'env': ''}
        with patch('rich.prompt.Prompt.ask', return_value='mykey'):
            result = _collect_api_key(_quiet_console(), preset)
        assert result == 'mykey'

    def test_env_var_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv('OPENAI_API_KEY', 'sk-secret')
        preset = {'env': 'OPENAI_API_KEY'}
        result = _collect_api_key(_quiet_console(), preset)
        assert result == 'sk-secret'

    def test_env_var_not_set_user_provides_key(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv('MY_UNIQUE_KEY_XYZ', raising=False)
        preset = {'env': 'MY_UNIQUE_KEY_XYZ'}
        with patch('rich.prompt.Prompt.ask', return_value='user-key'):
            result = _collect_api_key(_quiet_console(), preset)
        assert result == 'user-key'

    def test_env_var_not_set_user_leaves_blank(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv('MY_UNIQUE_KEY_XYZ', raising=False)
        preset = {'env': 'MY_UNIQUE_KEY_XYZ'}
        with patch('rich.prompt.Prompt.ask', return_value=''):
            result = _collect_api_key(_quiet_console(), preset)
        assert result == ''


class TestRunInit:
    @pytest.fixture(autouse=True)
    def _skip_connection_validation(self) -> None:
        with patch('backend.cli.onboarding.init_wizard.validate_connection'):
            yield

    def _patch_prompts(
        self,
        provider: str = 'openai',
        model: str = 'openai/gpt-4o-mini',
        api_key: str = 'sk-test',
        base_url: str = '',
    ):
        """Return a context-manager-like patch stack for Prompt/Confirm."""
        return [
            patch('backend.cli.onboarding.init_wizard._detect_local', return_value=[]),
            patch(
                'rich.prompt.Prompt.ask',
                side_effect=[provider, model, api_key, base_url],
            ),
        ]

    def test_new_settings_written(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        console = _quiet_console()
        settings_file = tmp_path / 'settings.json'
        monkeypatch.delenv('OPENAI_API_KEY', raising=False)
        with (
            patch('backend.cli.onboarding.init_wizard._detect_local', return_value=[]),
            patch(
                'rich.prompt.Prompt.ask',
                side_effect=['openai', 'openai/gpt-4o-mini', 'sk-test', ''],
            ),
            _patch_settings_path(settings_file),
        ):
            rc = run_init(project_root=tmp_path, console=console)
        assert rc == 0
        assert settings_file.exists()
        data = json.loads(settings_file.read_text(encoding='utf-8'))
        assert data['llm_provider'] == 'openai'
        assert data['llm_model'] == 'openai/gpt-4o-mini'
        assert data['llm_api_key'] == '${LLM_API_KEY}'
        assert (tmp_path / '.env').read_text(
            encoding='utf-8'
        ) == 'LLM_API_KEY=sk-test\n'

    def test_blank_cloud_key_writes_placeholder_without_fake_env(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        console = _quiet_console()
        settings_file = tmp_path / 'settings.json'
        monkeypatch.delenv('OPENAI_API_KEY', raising=False)
        with (
            patch('backend.cli.onboarding.init_wizard._detect_local', return_value=[]),
            patch(
                'rich.prompt.Prompt.ask',
                side_effect=['openai', 'openai/gpt-4o-mini', '', ''],
            ),
            _patch_settings_path(settings_file),
        ):
            rc = run_init(project_root=tmp_path, console=console)

        assert rc == 0
        data = json.loads(settings_file.read_text(encoding='utf-8'))
        assert data['llm_api_key'] == '${LLM_API_KEY}'
        assert not (tmp_path / '.env').exists()
        assert 'LLM_API_KEY' not in os.environ

    def test_provider_env_key_is_copied_to_generic_dotenv(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        console = _quiet_console()
        settings_file = tmp_path / 'settings.json'
        monkeypatch.setenv('OPENAI_API_KEY', 'sk-from-env')
        with (
            patch('backend.cli.onboarding.init_wizard._detect_local', return_value=[]),
            patch(
                'rich.prompt.Prompt.ask',
                side_effect=['openai', 'openai/gpt-4o-mini', ''],
            ),
            _patch_settings_path(settings_file),
        ):
            rc = run_init(project_root=tmp_path, console=console)

        assert rc == 0
        data = json.loads(settings_file.read_text(encoding='utf-8'))
        assert data['llm_api_key'] == '${LLM_API_KEY}'
        assert (tmp_path / '.env').read_text(
            encoding='utf-8'
        ) == 'LLM_API_KEY=sk-from-env\n'

    def test_existing_settings_declined(self, tmp_path: Path) -> None:
        console = _quiet_console()
        settings_file = tmp_path / 'settings.json'
        settings_file.write_text(
            json.dumps({'llm_model': 'x', 'llm_provider': 'y'}), encoding='utf-8'
        )
        with (
            patch('rich.prompt.Confirm.ask', return_value=False),
            _patch_settings_path(settings_file),
        ):
            rc = run_init(project_root=tmp_path, console=console)
        assert rc == 0
        # Original file untouched
        data = json.loads(settings_file.read_text(encoding='utf-8'))
        assert data['llm_model'] == 'x'

    def test_existing_settings_overwritten(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        console = _quiet_console()
        settings_file = tmp_path / 'settings.json'
        monkeypatch.delenv('ANTHROPIC_API_KEY', raising=False)
        settings_file.write_text(
            json.dumps({'llm_model': 'old', 'llm_provider': 'old'}), encoding='utf-8'
        )
        with (
            patch('rich.prompt.Confirm.ask', return_value=True),
            patch('backend.cli.onboarding.init_wizard._detect_local', return_value=[]),
            patch(
                'rich.prompt.Prompt.ask',
                side_effect=[
                    'anthropic',
                    'anthropic/claude-sonnet-4-20250514',
                    'key123',
                    '',
                ],
            ),
            _patch_settings_path(settings_file),
        ):
            rc = run_init(project_root=tmp_path, console=console)
        assert rc == 0
        data = json.loads(settings_file.read_text(encoding='utf-8'))
        assert data['llm_provider'] == 'anthropic'

    def test_ollama_detected_as_default(self, tmp_path: Path) -> None:
        console = _quiet_console()
        settings_file = tmp_path / 'settings.json'
        with (
            patch(
                'backend.cli.onboarding.init_wizard._detect_local',
                return_value=['ollama'],
            ),
            patch(
                'rich.prompt.Prompt.ask',
                side_effect=['ollama', 'ollama/llama3.2', '', 'http://localhost:11434'],
            ),
            _patch_settings_path(settings_file),
        ):
            rc = run_init(project_root=tmp_path, console=console)
        assert rc == 0
        data = json.loads(settings_file.read_text(encoding='utf-8'))
        assert data['llm_api_key'] == ''
        assert not (tmp_path / '.env').exists()

    def test_lm_studio_detected_as_default(self, tmp_path: Path) -> None:
        console = _quiet_console()
        settings_file = tmp_path / 'settings.json'
        with (
            patch(
                'backend.cli.onboarding.init_wizard._detect_local',
                return_value=['lm_studio'],
            ),
            patch(
                'rich.prompt.Prompt.ask',
                side_effect=[
                    'lm_studio',
                    'lm_studio/local-model',
                    '',
                    'http://localhost:1234/v1',
                ],
            ),
            _patch_settings_path(settings_file),
        ):
            rc = run_init(project_root=tmp_path, console=console)

        assert rc == 0
        data = json.loads(settings_file.read_text(encoding='utf-8'))
        assert data['llm_provider'] == 'lm_studio'
        assert data['llm_model'] == 'lm_studio/local-model'

    def test_security_checklist_shown_if_exists(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        console = _quiet_console()
        settings_file = tmp_path / 'settings.json'
        monkeypatch.delenv('OPENAI_API_KEY', raising=False)
        docs = tmp_path / 'docs'
        docs.mkdir()
        (docs / 'SECURITY_CHECKLIST.md').write_text('checklist', encoding='utf-8')
        with (
            patch('backend.cli.onboarding.init_wizard._detect_local', return_value=[]),
            patch(
                'rich.prompt.Prompt.ask',
                side_effect=['openai', 'openai/gpt-4o-mini', 'sk', ''],
            ),
            _patch_settings_path(settings_file),
        ):
            rc = run_init(project_root=tmp_path, console=console)
        assert rc == 0

    def test_default_project_root_is_cwd(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        console = _quiet_console()
        settings_file = tmp_path / 'settings.json'
        with (
            patch('backend.cli.onboarding.init_wizard._detect_local', return_value=[]),
            patch(
                'rich.prompt.Prompt.ask',
                side_effect=['openai', 'openai/gpt-4o-mini', 'sk', ''],
            ),
            _patch_settings_path(settings_file),
        ):
            rc = run_init(console=console)
        assert rc == 0
        assert settings_file.exists()
