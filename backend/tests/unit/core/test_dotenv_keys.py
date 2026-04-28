"""Tests for backend.core.config.dotenv_keys."""

from __future__ import annotations

import os

from backend.core.config.dotenv_keys import persist_llm_api_key_to_dotenv


class TestPersistLlmApiKeyToDotenv:
    def test_creates_env_file_and_updates_process_environment(self, tmp_path, monkeypatch):
        settings_path = tmp_path / 'settings.json'
        settings_path.write_text('{}', encoding='utf-8')
        monkeypatch.delenv('LLM_API_KEY', raising=False)

        env_path = persist_llm_api_key_to_dotenv(
            'secret-value',
            settings_json_path=settings_path,
        )

        assert env_path == tmp_path / '.env'
        assert env_path.read_text(encoding='utf-8') == 'LLM_API_KEY=secret-value\n'
        assert os.environ.get('LLM_API_KEY') == 'secret-value'

    def test_replaces_existing_llm_api_key_lines_once(self, tmp_path, monkeypatch):
        settings_path = tmp_path / 'settings.json'
        settings_path.write_text('{}', encoding='utf-8')
        env_path = tmp_path / '.env'
        env_path.write_text(
            'FIRST=1\nLLM_API_KEY=old\nexport LLM_API_KEY=older\nSECOND=2\n',
            encoding='utf-8',
        )
        monkeypatch.delenv('LLM_API_KEY', raising=False)

        persist_llm_api_key_to_dotenv(
            'new-secret',
            settings_json_path=settings_path,
        )

        assert env_path.read_text(encoding='utf-8') == (
            'FIRST=1\nLLM_API_KEY=new-secret\nSECOND=2\n'
        )
        assert os.environ.get('LLM_API_KEY') == 'new-secret'

    def test_appends_when_missing_and_preserves_terminal_newline(self, tmp_path):
        settings_path = tmp_path / 'settings.json'
        settings_path.write_text('{}', encoding='utf-8')
        env_path = tmp_path / '.env'
        env_path.write_text('FIRST=1', encoding='utf-8')

        persist_llm_api_key_to_dotenv(
            'another-secret',
            settings_json_path=settings_path,
            update_process_environ=False,
        )

        assert env_path.read_text(encoding='utf-8') == (
            'FIRST=1\nLLM_API_KEY=another-secret\n'
        )

    def test_blank_key_writes_empty_assignment_without_env_update(
        self, tmp_path, monkeypatch
    ):
        settings_path = tmp_path / 'settings.json'
        settings_path.write_text('{}', encoding='utf-8')
        monkeypatch.setenv('LLM_API_KEY', 'existing')

        env_path = persist_llm_api_key_to_dotenv(
            '   ',
            settings_json_path=settings_path,
        )

        assert env_path.read_text(encoding='utf-8') == 'LLM_API_KEY=\n'
        assert os.environ.get('LLM_API_KEY') == 'existing'
