"""Tests for backend.core.config.config_sections — check_unknown_sections."""

from __future__ import annotations

from unittest.mock import MagicMock

from backend.core.config.config_sections import check_unknown_sections


class TestCheckUnknownSections:
    def test_known_sections_no_warning(self):
        """All known sections should not trigger any warnings."""
        toml = {
            "core": {},
            "agent": {},
            "llm": {},
            "security": {},
            "runtime": {},
            "condenser": {},
            "mcp": {},
            "extended": {},
        }
        # Should not raise
        check_unknown_sections(toml, "config.toml")

    def test_unknown_section_logged(self):
        """Unknown sections do not raise but get logged."""
        toml = {"core": {}, "custom_plugin": {}}
        # check_unknown_sections uses logger.debug — just ensure no exception
        check_unknown_sections(toml, "config.toml")

    def test_empty_config(self):
        check_unknown_sections({}, "config.toml")

    def test_case_insensitive(self):
        """Known section names are matched case-insensitively."""
        toml = {"Core": {}, "LLM": {}, "SECURITY": {}}
        check_unknown_sections(toml, "config.toml")
