"""Pytest fixtures for Headless TUI."""

from backend.tests.unit.cli.tui._shared import *  # noqa: F403

@pytest.fixture(autouse=True)
def isolate_repo_settings(tmp_path, monkeypatch):
    """Never let headless TUI tests read or write repo-root settings.json."""
    settings_file = tmp_path / 'settings.json'
    settings_file.write_text(
        '{"llm_provider":"openai","llm_model":"openai/gpt-4o","llm_api_key":"${LLM_API_KEY}"}\n',
        encoding='utf-8',
    )
    monkeypatch.setattr(
        'backend.cli.settings.storage._settings_path',
        lambda: settings_file,
    )
@pytest.fixture
def mock_config():
    config = MagicMock()
    type(config).project_root = PropertyMock(return_value=None)

    llm_config = MagicMock()
    llm_config.model = 'openai/gpt-4o'
    llm_config.base_url = None
    llm_config.custom_llm_provider = 'openai'
    llm_config.reasoning_effort = None
    config.get_llm_config.return_value = llm_config
    config.get_llm_config_from_agent.return_value = llm_config
    return config
