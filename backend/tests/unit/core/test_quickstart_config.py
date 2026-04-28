"""Tests for backend.core.config.quickstart — generate_quickstart_config."""

from __future__ import annotations

import json
from unittest.mock import Mock

import backend.core.config.quickstart as quickstart
from backend.core.constants import LLM_API_KEY_SETTINGS_PLACEHOLDER


class TestGenerateQuickstartConfig:
    def test_default_values(self):
        result = quickstart.generate_quickstart_config()
        data = json.loads(result)
        assert data['llm_api_key'] == LLM_API_KEY_SETTINGS_PLACEHOLDER
        assert data['llm_model'] == 'gemini-2.5-flash'
        assert data['max_budget_per_task'] == 5.0
        assert data['llm_base_url'] == ''
        assert data['project_root'] == './workspace'

    def test_custom_model(self):
        result = quickstart.generate_quickstart_config(model='gpt-4o')
        data = json.loads(result)
        assert data['llm_model'] == 'gpt-4o'

    def test_custom_base_url(self):
        result = quickstart.generate_quickstart_config(base_url='https://api.example.com')
        data = json.loads(result)
        assert data['llm_base_url'] == 'https://api.example.com'

    def test_custom_budget(self):
        result = quickstart.generate_quickstart_config(max_budget=10.0)
        data = json.loads(result)
        assert data['max_budget_per_task'] == 10.0

    def test_empty_base_url_commented(self):
        result = quickstart.generate_quickstart_config(base_url='')
        data = json.loads(result)
        assert data['llm_base_url'] == ''

    def test_all_custom(self):
        result = quickstart.generate_quickstart_config(
            model='llama3',
            base_url='http://localhost:11434',
            max_budget=1.0,
        )
        data = json.loads(result)
        assert data['llm_api_key'] == LLM_API_KEY_SETTINGS_PLACEHOLDER
        assert data['llm_model'] == 'llama3'
        assert data['llm_base_url'] == 'http://localhost:11434'
        assert data['max_budget_per_task'] == 1.0


class TestInteractiveInit:
    @staticmethod
    def _patch_inputs(monkeypatch, responses: list[str]) -> None:
        answers = iter(responses)
        monkeypatch.setattr('builtins.input', lambda _prompt='': next(answers))

    def test_aborts_when_existing_file_is_not_overwritten(
        self,
        tmp_path,
        monkeypatch,
        capsys,
    ):
        dest = tmp_path / 'settings.json'
        dest.write_text('{"existing": true}', encoding='utf-8')
        monkeypatch.setattr(quickstart, 'discover_all_local_models', lambda: {})
        self._patch_inputs(monkeypatch, ['n'])

        quickstart._interactive_init(dest)

        assert dest.read_text(encoding='utf-8') == '{"existing": true}'
        assert not (tmp_path / 'workspace').exists()
        assert 'Aborted.' in capsys.readouterr().out

    def test_overwrites_existing_file_persists_api_key_and_creates_workspace(
        self,
        tmp_path,
        monkeypatch,
        capsys,
    ):
        dest = tmp_path / 'settings.json'
        dest.write_text('{"existing": true}', encoding='utf-8')
        monkeypatch.setattr(quickstart, 'discover_all_local_models', lambda: {})
        persist_mock = Mock()
        monkeypatch.setattr(quickstart, 'persist_llm_api_key_to_dotenv', persist_mock)
        self._patch_inputs(monkeypatch, ['y', '', 'secret-key', '12.5'])

        quickstart._interactive_init(dest)

        data = json.loads(dest.read_text(encoding='utf-8'))
        assert data['llm_model'] == 'gemini-2.5-flash'
        assert data['max_budget_per_task'] == 12.5
        assert (tmp_path / 'workspace').is_dir()
        persist_mock.assert_called_once_with(
            'secret-key',
            settings_json_path=dest,
        )
        output = capsys.readouterr().out
        assert 'Configuration saved to' in output
        assert 'Workspace initialized at' in output

    def test_uses_local_model_suggestion_and_skips_api_key_prompt(
        self,
        tmp_path,
        monkeypatch,
        capsys,
    ):
        dest = tmp_path / 'settings.json'
        monkeypatch.setattr(
            quickstart,
            'discover_all_local_models',
            lambda: {'ollama': ['llama3', 'mistral']},
        )
        persist_mock = Mock()
        monkeypatch.setattr(quickstart, 'persist_llm_api_key_to_dotenv', persist_mock)
        self._patch_inputs(monkeypatch, ['', '7.5'])

        quickstart._interactive_init(dest)

        data = json.loads(dest.read_text(encoding='utf-8'))
        assert data['llm_model'] == 'ollama/llama3'
        assert data['max_budget_per_task'] == 7.5
        persist_mock.assert_not_called()
        output = capsys.readouterr().out
        assert 'Found local models!' in output
        assert 'ollama: llama3, mistral' in output


class TestQuickstartMain:
    def test_main_uses_app_project_root(self, tmp_path, monkeypatch):
        captured_destinations: list[object] = []

        monkeypatch.setenv('APP_PROJECT_ROOT', str(tmp_path))
        monkeypatch.setattr(
            quickstart,
            '_interactive_init',
            lambda dest: captured_destinations.append(dest),
        )

        quickstart.main()

        assert captured_destinations == [tmp_path / 'settings.json']
