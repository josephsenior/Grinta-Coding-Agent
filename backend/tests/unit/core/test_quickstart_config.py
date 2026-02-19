"""Tests for backend.core.config.quickstart — generate_quickstart_config."""

from __future__ import annotations

from backend.core.config.quickstart import generate_quickstart_config


class TestGenerateQuickstartConfig:
    def test_default_values(self):
        result = generate_quickstart_config()
        assert "[core]" in result
        assert "[llm]" in result
        assert "[agent]" in result
        assert 'api_key = ""' in result
        assert "claude-sonnet-4-20250514" in result
        assert "max_budget_per_task = 5.0" in result
        # No base_url by default — should be commented out
        assert '# base_url = ""' in result

    def test_custom_api_key(self):
        result = generate_quickstart_config(api_key="sk-test123")
        assert 'api_key = "sk-test123"' in result

    def test_custom_model(self):
        result = generate_quickstart_config(model="gpt-4o")
        assert 'model = "gpt-4o"' in result

    def test_custom_base_url(self):
        result = generate_quickstart_config(base_url="https://api.example.com")
        assert 'base_url = "https://api.example.com"' in result
        # Should NOT be commented out
        assert "# base_url" not in result

    def test_custom_budget(self):
        result = generate_quickstart_config(max_budget=10.0)
        assert "max_budget_per_task = 10.0" in result

    def test_empty_base_url_commented(self):
        result = generate_quickstart_config(base_url="")
        assert '# base_url = ""' in result

    def test_all_custom(self):
        result = generate_quickstart_config(
            api_key="key1",
            model="llama3",
            base_url="http://localhost:11434",
            max_budget=1.0,
        )
        assert 'api_key = "key1"' in result
        assert 'model = "llama3"' in result
        assert 'base_url = "http://localhost:11434"' in result
        assert "max_budget_per_task = 1.0" in result
