"""Tests for backend.core.config.quickstart — generate_quickstart_config."""

from __future__ import annotations

import json

from backend.core.config.quickstart import generate_quickstart_config


class TestGenerateQuickstartConfig:
    def test_default_values(self):
        result = generate_quickstart_config()
        data = json.loads(result)
        assert data["llm_api_key"] == ""
        assert data["llm_model"] == "gemini-2.5-flash"
        assert data["max_budget_per_task"] == 5.0
        assert data["llm_base_url"] == ""
        assert data["project_root"] == "./workspace"

    def test_custom_api_key(self):
        result = generate_quickstart_config(api_key="sk-test123")
        data = json.loads(result)
        assert data["llm_api_key"] == "sk-test123"

    def test_custom_model(self):
        result = generate_quickstart_config(model="gpt-4o")
        data = json.loads(result)
        assert data["llm_model"] == "gpt-4o"

    def test_custom_base_url(self):
        result = generate_quickstart_config(base_url="https://api.example.com")
        data = json.loads(result)
        assert data["llm_base_url"] == "https://api.example.com"

    def test_custom_budget(self):
        result = generate_quickstart_config(max_budget=10.0)
        data = json.loads(result)
        assert data["max_budget_per_task"] == 10.0

    def test_empty_base_url_commented(self):
        result = generate_quickstart_config(base_url="")
        data = json.loads(result)
        assert data["llm_base_url"] == ""

    def test_all_custom(self):
        result = generate_quickstart_config(
            api_key="key1",
            model="llama3",
            base_url="http://localhost:11434",
            max_budget=1.0,
        )
        data = json.loads(result)
        assert data["llm_api_key"] == "key1"
        assert data["llm_model"] == "llama3"
        assert data["llm_base_url"] == "http://localhost:11434"
        assert data["max_budget_per_task"] == 1.0
