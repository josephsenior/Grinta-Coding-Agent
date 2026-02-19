"""Tests for backend.core.plugin_template module.

Targets 0% coverage (28 statements).
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from backend.core.plugin import PluginRegistry
from backend.core.plugin_template import MyPlugin, register


class TestMyPlugin:
    def test_name_set(self):
        plugin = MyPlugin()
        assert plugin.name == "my-plugin"

    def test_version_set(self):
        plugin = MyPlugin()
        assert plugin.version == "0.1.0"

    def test_description_set(self):
        plugin = MyPlugin()
        assert plugin.description

    @pytest.mark.asyncio
    async def test_on_action_pre_returns_action(self):
        plugin = MyPlugin()
        action = MagicMock()
        result = await plugin.on_action_pre(action)
        assert result is action

    @pytest.mark.asyncio
    async def test_on_event_no_error(self):
        plugin = MyPlugin()
        await plugin.on_event(MagicMock())

    @pytest.mark.asyncio
    async def test_on_session_start(self):
        plugin = MyPlugin()
        await plugin.on_session_start("sid", {"key": "val"})

    @pytest.mark.asyncio
    async def test_on_session_end(self):
        plugin = MyPlugin()
        await plugin.on_session_end("sid", {})

    def test_validate_no_warnings(self):
        result = MyPlugin().validate()
        assert result == []


class TestRegister:
    def test_registers_plugin(self):
        registry = PluginRegistry()
        register(registry)
        assert registry.get_plugin("my-plugin") is not None

    def test_registered_is_my_plugin(self):
        registry = PluginRegistry()
        register(registry)
        assert isinstance(registry.get_plugin("my-plugin"), MyPlugin)
