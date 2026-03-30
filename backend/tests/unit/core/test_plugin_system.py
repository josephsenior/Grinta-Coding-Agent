"""Tests for backend.core.plugin module — PluginRegistry, AppPlugin, hooks dispatch."""

from __future__ import annotations

from typing import Any, cast
import unittest
from unittest.mock import AsyncMock, MagicMock

from backend.core.plugin import (
    AppPlugin,
    HookType,
    PluginRegistry,
)


class _SimplePlugin(AppPlugin):
    """Concrete plugin for testing."""

    name = "test-plugin"
    version = "1.0.0"
    description = "A test plugin"

    async def on_event(self, event):
        pass

    async def on_session_start(self, session_id, metadata):
        pass

    async def on_session_end(self, session_id, metadata):
        pass


class _ActionPlugin(AppPlugin):
    """Plugin that modifies actions."""

    name = "action-plugin"
    version = "0.1.0"
    description = "Modifies actions"

    async def on_action_pre(self, action):
        action.modified = True
        return action

    async def on_action_post(self, action, observation):
        observation.modified = True
        return observation

    async def on_event(self, event):
        pass

    async def on_session_start(self, session_id, metadata):
        pass

    async def on_session_end(self, session_id, metadata):
        pass


class TestHookType(unittest.TestCase):
    def test_values(self):
        self.assertEqual(HookType.ACTION_PRE, "action_pre")
        self.assertEqual(HookType.LLM_POST, "llm_post")
        self.assertEqual(HookType.TOOL_INVOKE, "tool_invoke")


class TestAppPluginBase(unittest.TestCase):
    def test_repr(self):
        p = _SimplePlugin()
        self.assertIn("test-plugin", repr(p))
        self.assertIn("1.0.0", repr(p))

    def test_validate_default_name(self):
        class Unnamed(AppPlugin):
            async def on_event(self, event):
                pass

            async def on_session_start(self, sid, m):
                pass

            async def on_session_end(self, sid, m):
                pass

        p = Unnamed()
        warnings = p.validate()
        self.assertTrue(any("unnamed-plugin" in w for w in warnings))

    def test_validate_default_version(self):
        class NoVer(AppPlugin):
            name = "good-name"

            async def on_event(self, event):
                pass

            async def on_session_start(self, sid, m):
                pass

            async def on_session_end(self, sid, m):
                pass

        warnings = NoVer().validate()
        self.assertTrue(any("0.0.0" in w for w in warnings))

    def test_validate_no_description(self):
        class NoDesc(AppPlugin):
            name = "good"
            version = "1.0"

            async def on_event(self, event):
                pass

            async def on_session_start(self, sid, m):
                pass

            async def on_session_end(self, sid, m):
                pass

        warnings = NoDesc().validate()
        self.assertTrue(any("description" in w.lower() for w in warnings))

    def test_validate_all_good(self):
        p = _SimplePlugin()
        warnings = p.validate()
        self.assertEqual(warnings, [])


class TestPluginRegistry(unittest.TestCase):
    def test_register_and_get(self):
        reg = PluginRegistry()
        p = _SimplePlugin()
        reg.register(p)
        self.assertIs(reg.get_plugin("test-plugin"), p)
        self.assertEqual(len(reg.plugins), 1)

    def test_duplicate_skipped(self):
        reg = PluginRegistry()
        reg.register(_SimplePlugin())
        reg.register(_SimplePlugin())
        self.assertEqual(len(reg.plugins), 1)

    def test_unregister(self):
        reg = PluginRegistry()
        reg.register(_SimplePlugin())
        reg.unregister("test-plugin")
        self.assertIsNone(reg.get_plugin("test-plugin"))
        self.assertEqual(len(reg.plugins), 0)

    def test_unregister_missing_no_error(self):
        reg = PluginRegistry()
        reg.unregister("nonexistent")  # Should not raise

    def test_incompatible_version_rejected(self):
        class FuturePlugin(AppPlugin):
            name = "future"
            version = "1.0"
            min_api_version = (99, 99)

            async def on_event(self, event):
                pass

            async def on_session_start(self, sid, m):
                pass

            async def on_session_end(self, sid, m):
                pass

        reg = PluginRegistry()
        reg.register(FuturePlugin())
        self.assertIsNone(reg.get_plugin("future"))

    def test_validate_all(self):
        reg = PluginRegistry()
        reg.register(_SimplePlugin())

        class Bad(AppPlugin):
            name = "bad"
            version = "1.0"
            description = "test"

            async def on_event(self, event):
                pass

            async def on_session_start(self, sid, m):
                pass

            async def on_session_end(self, sid, m):
                pass

            def validate(self):
                return ["something wrong"]

        reg.register(Bad())
        results = reg.validate_all()
        self.assertIn("bad", results)
        self.assertEqual(results["bad"], ["something wrong"])
        self.assertNotIn("test-plugin", results)


class TestPluginRegistryDispatch(unittest.IsolatedAsyncioTestCase):
    async def test_dispatch_action_pre(self):
        reg = PluginRegistry()
        reg.register(_ActionPlugin())
        action = MagicMock()
        result = await reg.dispatch_action_pre(action)
        self.assertIsNotNone(result)
        self.assertTrue(cast(Any, result).modified)

    async def test_dispatch_action_post(self):
        reg = PluginRegistry()
        reg.register(_ActionPlugin())
        action = MagicMock()
        obs = MagicMock()
        result = await reg.dispatch_action_post(action, obs)
        self.assertIsNotNone(result)
        self.assertTrue(cast(Any, result).modified)

    async def test_dispatch_event(self):
        reg = PluginRegistry()
        plugin = MagicMock(spec=_SimplePlugin)
        plugin.name = "mock"
        plugin.min_api_version = (1, 0)
        plugin.on_event = AsyncMock()
        reg.register(plugin)
        event = MagicMock()
        await reg.dispatch_event(event)
        plugin.on_event.assert_awaited_once_with(event)

    async def test_dispatch_session_start(self):
        reg = PluginRegistry()
        plugin = MagicMock(spec=_SimplePlugin)
        plugin.name = "mock"
        plugin.min_api_version = (1, 0)
        plugin.on_session_start = AsyncMock()
        reg.register(plugin)
        await reg.dispatch_session_start("sess-1", {"key": "val"})
        plugin.on_session_start.assert_awaited_once()

    async def test_dispatch_session_end(self):
        reg = PluginRegistry()
        plugin = MagicMock(spec=_SimplePlugin)
        plugin.name = "mock"
        plugin.min_api_version = (1, 0)
        plugin.on_session_end = AsyncMock()
        reg.register(plugin)
        await reg.dispatch_session_end("sess-1")
        plugin.on_session_end.assert_awaited_once()

    async def test_dispatch_llm_pre(self):
        reg = PluginRegistry()
        p = _SimplePlugin()
        reg.register(p)
        msgs = [{"role": "user", "content": "hi"}]
        result = await reg.dispatch_llm_pre(msgs)
        self.assertEqual(result, msgs)

    async def test_dispatch_llm_post(self):
        reg = PluginRegistry()
        p = _SimplePlugin()
        reg.register(p)
        resp: dict[str, Any] = {"choices": []}
        result = await reg.dispatch_llm_post(resp)
        self.assertEqual(result, resp)

    async def test_dispatch_condense(self):
        reg = PluginRegistry()
        p = _SimplePlugin()
        reg.register(p)
        result = await reg.dispatch_condense(["orig"], ["condensed"], {"type": "x"})
        self.assertEqual(result, ["condensed"])

    async def test_dispatch_memory_recall(self):
        reg = PluginRegistry()
        p = _SimplePlugin()
        reg.register(p)
        result = await reg.dispatch_memory_recall("workspace_context", {"data": 1})
        self.assertEqual(result, {"data": 1})

    async def test_dispatch_tool_invoke(self):
        reg = PluginRegistry()
        p = _SimplePlugin()
        reg.register(p)
        result = await reg.dispatch_tool_invoke("run_cmd", {"cmd": "ls"})
        self.assertEqual(result, {"cmd": "ls"})

    async def test_dispatch_exception_handled(self):
        """Plugin exceptions should be caught, not propagated."""
        reg = PluginRegistry()
        plugin = MagicMock(spec=_SimplePlugin)
        plugin.name = "broken"
        plugin.min_api_version = (1, 0)
        plugin.on_event = AsyncMock(side_effect=RuntimeError("boom"))
        reg.register(plugin)
        # Should not raise
        await reg.dispatch_event(MagicMock())

    async def test_dispatch_chains_multiple_plugins(self):
        reg = PluginRegistry()

        class P1(_SimplePlugin):
            name = "p1"

            async def on_llm_pre(self, messages, **kwargs):
                messages.append({"role": "system", "content": "from p1"})
                return messages

        class P2(_SimplePlugin):
            name = "p2"

            async def on_llm_pre(self, messages, **kwargs):
                messages.append({"role": "system", "content": "from p2"})
                return messages

        reg.register(P1())
        reg.register(P2())
        result = await reg.dispatch_llm_pre([])
        self.assertEqual(len(result), 2)


class TestPluginTemplate(unittest.IsolatedAsyncioTestCase):
    async def test_my_plugin_hooks(self):
        from backend.core.plugin_template import MyPlugin

        p = MyPlugin()
        self.assertEqual(p.name, "my-plugin")
        self.assertEqual(p.version, "0.1.0")

        # on_action_pre returns action unchanged
        action = MagicMock()
        result = await p.on_action_pre(action)
        self.assertIs(result, action)

        # on_event is a no-op
        await p.on_event(MagicMock())

        # session hooks
        await p.on_session_start("sess-1", {})
        await p.on_session_end("sess-1", {})

    def test_register_function(self):
        from backend.core.plugin_template import register

        reg = PluginRegistry()
        register(reg)
        self.assertIsNotNone(reg.get_plugin("my-plugin"))

    def test_validate(self):
        from backend.core.plugin_template import MyPlugin

        warnings = MyPlugin().validate()
        self.assertEqual(warnings, [])


if __name__ == "__main__":
    unittest.main()
