"""Tests for backend.core.plugin module (PluginRegistry, ForgePlugin).

Targets low coverage in plugin.py.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from backend.core.plugin import (
    PLUGIN_API_VERSION,
    PLUGIN_COMPAT_WINDOW,
    ForgePlugin,
    HookType,
    PluginRegistry,
)


# -----------------------------------------------------------
# Concrete plugin stub
# -----------------------------------------------------------

class _SimplePlugin(ForgePlugin):
    name = "simple-plugin"
    version = "1.0.0"
    description = "A test plugin"

    async def on_event(self, event: Any) -> None:
        pass

    async def on_session_start(self, session_id: str, metadata: dict) -> None:
        pass

    async def on_session_end(self, session_id: str, metadata: dict) -> None:
        pass


class _MutatingPlugin(ForgePlugin):
    name = "mutating-plugin"
    version = "1.0.0"
    description = "Mutates data"

    async def on_event(self, event: Any) -> None:
        pass

    async def on_session_start(self, session_id: str, metadata: dict) -> None:
        pass

    async def on_session_end(self, session_id: str, metadata: dict) -> None:
        pass

    async def on_action_pre(self, action: Any) -> Any:
        action.mutated = True
        return action

    async def on_llm_pre(self, messages, **kwargs):
        messages.append({"role": "system", "content": "injected"})
        return messages

    async def on_tool_invoke(self, tool_name, tool_args):
        tool_args["injected"] = True
        return tool_args


class _RaisingPlugin(ForgePlugin):
    name = "raising-plugin"
    version = "1.0.0"
    description = "Always raises"

    async def on_event(self, event: Any) -> None:
        raise RuntimeError("event error")

    async def on_session_start(self, session_id: str, metadata: dict) -> None:
        raise RuntimeError("session start error")

    async def on_session_end(self, session_id: str, metadata: dict) -> None:
        raise RuntimeError("session end error")

    async def on_action_pre(self, action: Any) -> Any:
        raise RuntimeError("action_pre error")


@pytest.fixture()
def registry() -> PluginRegistry:
    return PluginRegistry()


# -----------------------------------------------------------
# HookType
# -----------------------------------------------------------

class TestHookType:
    def test_all_hook_types_present(self):
        hook_names = {h.value for h in HookType}
        assert "action_pre" in hook_names
        assert "session_start" in hook_names
        assert "tool_invoke" in hook_names


# -----------------------------------------------------------
# PluginRegistry.register
# -----------------------------------------------------------

class TestPluginRegistryRegister:
    def test_register_plugin(self, registry: PluginRegistry):
        plugin = _SimplePlugin()
        registry.register(plugin)
        assert registry.get_plugin("simple-plugin") is plugin

    def test_duplicate_skipped(self, registry: PluginRegistry):
        p1 = _SimplePlugin()
        p2 = _SimplePlugin()
        registry.register(p1)
        registry.register(p2)
        assert len(registry.plugins) == 1
        assert registry.get_plugin("simple-plugin") is p1

    def test_incompatible_version_rejected(self, registry: PluginRegistry):
        plugin = _SimplePlugin()
        plugin.min_api_version = (999, 0)
        registry.register(plugin)
        assert registry.get_plugin("simple-plugin") is None

    def test_unregister_plugin(self, registry: PluginRegistry):
        registry.register(_SimplePlugin())
        registry.unregister("simple-plugin")
        assert registry.get_plugin("simple-plugin") is None

    def test_unregister_nonexistent_no_error(self, registry: PluginRegistry):
        registry.unregister("nonexistent")  # should not raise

    def test_plugins_property(self, registry: PluginRegistry):
        registry.register(_SimplePlugin())
        assert len(registry.plugins) == 1


# -----------------------------------------------------------
# Dispatch hooks
# -----------------------------------------------------------

class TestDispatchHooks:
    @pytest.mark.asyncio
    async def test_dispatch_action_pre_passes_through(self, registry: PluginRegistry):
        registry.register(_SimplePlugin())
        action = MagicMock()
        result = await registry.dispatch_action_pre(action)
        assert result is action

    @pytest.mark.asyncio
    async def test_dispatch_action_pre_mutates(self, registry: PluginRegistry):
        registry.register(_MutatingPlugin())
        action = MagicMock()
        result = await registry.dispatch_action_pre(action)
        assert result.mutated is True

    @pytest.mark.asyncio
    async def test_dispatch_action_pre_tolerates_exception(self, registry: PluginRegistry):
        registry.register(_RaisingPlugin())
        action = MagicMock()
        result = await registry.dispatch_action_pre(action)
        assert result is action  # returned unchanged after exception

    @pytest.mark.asyncio
    async def test_dispatch_action_post(self, registry: PluginRegistry):
        registry.register(_SimplePlugin())
        action = MagicMock()
        obs = MagicMock()
        result = await registry.dispatch_action_post(action, obs)
        assert result is obs

    @pytest.mark.asyncio
    async def test_dispatch_event_fan_out(self, registry: PluginRegistry):
        registry.register(_SimplePlugin())
        await registry.dispatch_event(MagicMock())  # no exception

    @pytest.mark.asyncio
    async def test_dispatch_event_tolerates_exception(self, registry: PluginRegistry):
        registry.register(_RaisingPlugin())
        await registry.dispatch_event(MagicMock())  # no exception raised

    @pytest.mark.asyncio
    async def test_dispatch_session_start(self, registry: PluginRegistry):
        registry.register(_SimplePlugin())
        await registry.dispatch_session_start("sid1", {"key": "val"})

    @pytest.mark.asyncio
    async def test_dispatch_session_start_tolerates_exception(self, registry: PluginRegistry):
        registry.register(_RaisingPlugin())
        await registry.dispatch_session_start("sid1")

    @pytest.mark.asyncio
    async def test_dispatch_session_end(self, registry: PluginRegistry):
        registry.register(_SimplePlugin())
        await registry.dispatch_session_end("sid1")

    @pytest.mark.asyncio
    async def test_dispatch_llm_pre_mutates(self, registry: PluginRegistry):
        registry.register(_MutatingPlugin())
        messages = [{"role": "user", "content": "hi"}]
        result = await registry.dispatch_llm_pre(messages)
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_dispatch_llm_post(self, registry: PluginRegistry):
        registry.register(_SimplePlugin())
        resp = {"choices": []}
        result = await registry.dispatch_llm_post(resp)
        assert result is resp

    @pytest.mark.asyncio
    async def test_dispatch_condense(self, registry: PluginRegistry):
        registry.register(_SimplePlugin())
        condensed = [1, 2, 3]
        result = await registry.dispatch_condense([1, 2, 3, 4], condensed, {})
        assert result == condensed

    @pytest.mark.asyncio
    async def test_dispatch_memory_recall(self, registry: PluginRegistry):
        registry.register(_SimplePlugin())
        content = {"docs": ["a", "b"]}
        result = await registry.dispatch_memory_recall("workspace_context", content)
        assert result is content

    @pytest.mark.asyncio
    async def test_dispatch_tool_invoke_mutates(self, registry: PluginRegistry):
        registry.register(_MutatingPlugin())
        result = await registry.dispatch_tool_invoke("my_tool", {"arg": "val"})
        assert result["injected"] is True

    @pytest.mark.asyncio
    async def test_no_plugins_dispatch_returns_input(self, registry: PluginRegistry):
        action = MagicMock()
        result = await registry.dispatch_action_pre(action)
        assert result is action


# -----------------------------------------------------------
# ForgePlugin.validate
# -----------------------------------------------------------

class TestForgePluginValidate:
    def test_no_warnings_when_configured(self):
        assert _SimplePlugin().validate() == []

    def test_default_name_warns(self):
        class _DefaultPlugin(ForgePlugin):
            async def on_event(self, e): pass
            async def on_session_start(self, s, m): pass
            async def on_session_end(self, s, m): pass

        p = _DefaultPlugin()
        warnings = p.validate()
        assert any("name" in w.lower() for w in warnings)

    def test_validate_all_empty(self, registry: PluginRegistry):
        registry.register(_SimplePlugin())
        result = registry.validate_all()
        assert "simple-plugin" not in result  # no warnings


# -----------------------------------------------------------
# ForgePlugin default hooks
# -----------------------------------------------------------

class TestForgePluginDefaultHooks:
    @pytest.mark.asyncio
    async def test_on_action_pre_passthrough(self):
        action = MagicMock()
        plugin = _SimplePlugin()
        assert await plugin.on_action_pre(action) is action

    @pytest.mark.asyncio
    async def test_on_action_post_passthrough(self):
        obs = MagicMock()
        plugin = _SimplePlugin()
        assert await plugin.on_action_post(MagicMock(), obs) is obs

    @pytest.mark.asyncio
    async def test_on_llm_post_passthrough(self):
        resp = {"choices": []}
        plugin = _SimplePlugin()
        assert await plugin.on_llm_post(resp) is resp

    @pytest.mark.asyncio
    async def test_on_condense_passthrough(self):
        condensed = [1, 2]
        plugin = _SimplePlugin()
        assert await plugin.on_condense([1, 2, 3], condensed, {}) is condensed

    @pytest.mark.asyncio
    async def test_on_memory_recall_passthrough(self):
        content = {"data": "x"}
        plugin = _SimplePlugin()
        assert await plugin.on_memory_recall("type", content) is content

    @pytest.mark.asyncio
    async def test_on_tool_invoke_passthrough(self):
        args = {"x": 1}
        plugin = _SimplePlugin()
        assert await plugin.on_tool_invoke("tool", args) is args

    def test_repr(self):
        assert "simple-plugin" in repr(_SimplePlugin())
