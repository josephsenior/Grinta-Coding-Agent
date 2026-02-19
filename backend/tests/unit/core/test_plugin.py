"""Unit tests for backend.core.plugin — plugin system + registry."""

from __future__ import annotations

import warnings
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from backend.core.plugin import (
    ForgePlugin,
    HookType,
    PLUGIN_API_VERSION,
    PLUGIN_COMPAT_WINDOW,
    PluginRegistry,
    discover_plugins,
    get_plugin_registry,
)


# ---------------------------------------------------------------------------
# Concrete test plugin (ForgePlugin is abstract)
# ---------------------------------------------------------------------------


class _TestPlugin(ForgePlugin):
    name = "test-plugin"
    version = "1.0.0"
    description = "A test plugin"

    async def on_event(self, event):
        pass

    async def on_session_start(self, session_id, metadata):
        pass

    async def on_session_end(self, session_id, metadata):
        pass


# ---------------------------------------------------------------------------
# HookType enum
# ---------------------------------------------------------------------------


class TestHookType:
    def test_has_expected_members(self):
        assert HookType.ACTION_PRE == "action_pre"
        assert HookType.LLM_POST == "llm_post"
        assert HookType.SESSION_START == "session_start"
        assert HookType.TOOL_INVOKE == "tool_invoke"


# ---------------------------------------------------------------------------
# ForgePlugin
# ---------------------------------------------------------------------------


class TestForgePlugin:
    def test_repr(self):
        p = _TestPlugin()
        r = repr(p)
        assert "test-plugin" in r
        assert "1.0.0" in r

    def test_validate_clean(self):
        p = _TestPlugin()
        assert p.validate() == []

    def test_validate_defaults_warn(self):
        class Bare(_TestPlugin):
            name = "unnamed-plugin"
            version = "0.0.0"
            description = ""

        w = Bare().validate()
        assert len(w) >= 2  # name + version + description

    async def test_on_action_pre_passthrough(self):
        p = _TestPlugin()
        sentinel = object()
        assert (await p.on_action_pre(sentinel)) is sentinel  # type: ignore[arg-type]

    async def test_on_llm_pre_passthrough(self):
        p = _TestPlugin()
        msgs = [{"role": "user", "content": "hi"}]
        result = await p.on_llm_pre(msgs)
        assert result is msgs

    async def test_on_tool_invoke_passthrough(self):
        p = _TestPlugin()
        args = {"x": 1}
        result = await p.on_tool_invoke("tool", args)
        assert result is args

    async def test_on_action_post_passthrough(self):
        p = _TestPlugin()
        obs = SimpleNamespace()
        result = await p.on_action_post(SimpleNamespace(), obs)
        assert result is obs

    async def test_on_llm_post_passthrough(self):
        p = _TestPlugin()
        resp = {"ok": True}
        result = await p.on_llm_post(resp)
        assert result is resp

    async def test_on_condense_passthrough(self):
        p = _TestPlugin()
        condensed = ["b"]
        result = await p.on_condense(["a"], condensed, {})
        assert result is condensed

    async def test_on_memory_recall_passthrough(self):
        p = _TestPlugin()
        content = {"x": 1}
        result = await p.on_memory_recall("knowledge", content)
        assert result is content

    async def test_abstract_hooks_raise(self):
        class Raises(ForgePlugin):
            async def on_event(self, event):
                return await super().on_event(event)

            async def on_session_start(self, session_id, metadata):
                return await super().on_session_start(session_id, metadata)

            async def on_session_end(self, session_id, metadata):
                return await super().on_session_end(session_id, metadata)

        p = Raises()
        with pytest.raises(NotImplementedError):
            await p.on_event(SimpleNamespace())
        with pytest.raises(NotImplementedError):
            await p.on_session_start("s", {})
        with pytest.raises(NotImplementedError):
            await p.on_session_end("s", {})


# ---------------------------------------------------------------------------
# PluginRegistry
# ---------------------------------------------------------------------------


class TestPluginRegistry:
    def test_register_and_list(self):
        reg = PluginRegistry()
        reg.register(_TestPlugin())
        assert len(reg.plugins) == 1
        assert reg.plugins[0].name == "test-plugin"

    def test_duplicate_skipped(self):
        reg = PluginRegistry()
        reg.register(_TestPlugin())
        reg.register(_TestPlugin())
        assert len(reg.plugins) == 1

    def test_get_plugin(self):
        reg = PluginRegistry()
        reg.register(_TestPlugin())
        assert reg.get_plugin("test-plugin") is not None
        assert reg.get_plugin("nope") is None

    def test_unregister(self):
        reg = PluginRegistry()
        reg.register(_TestPlugin())
        reg.unregister("test-plugin")
        assert not reg.plugins

    def test_unregister_missing(self):
        reg = PluginRegistry()
        reg.unregister("nope")  # should not raise

    def test_reject_incompatible_version(self):
        class FuturePlugin(_TestPlugin):
            name = "future"
            min_api_version = (999, 0)

        reg = PluginRegistry()
        reg.register(FuturePlugin())
        assert not reg.plugins

    def test_compat_window_deprecation_warning(self):
        """Plugins at the edge of compat window should emit DeprecationWarning."""
        host_major, host_minor = PLUGIN_API_VERSION
        # min_api_version that is exactly PLUGIN_COMPAT_WINDOW behind
        old_minor = max(0, host_minor - PLUGIN_COMPAT_WINDOW)

        class OldPlugin(_TestPlugin):
            name = "old"
            min_api_version = (host_major, old_minor)

        reg = PluginRegistry()
        if host_minor - old_minor >= PLUGIN_COMPAT_WINDOW:
            with warnings.catch_warnings(record=True) as w:
                warnings.simplefilter("always")
                reg.register(OldPlugin())
                assert any(issubclass(x.category, DeprecationWarning) for x in w)
        else:
            reg.register(OldPlugin())
        assert len(reg.plugins) == 1

    def test_deprecation_warning_for_old_version(self, monkeypatch):
        import backend.core.plugin as plugin_module

        monkeypatch.setattr(plugin_module, "PLUGIN_API_VERSION", (1, 5))
        monkeypatch.setattr(plugin_module, "PLUGIN_COMPAT_WINDOW", 2)

        class OldPlugin(_TestPlugin):
            name = "old-explicit"
            min_api_version = (1, 3)

        reg = PluginRegistry()
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            reg.register(OldPlugin())
            assert any(issubclass(x.category, DeprecationWarning) for x in w)

    def test_validate_all(self):
        class Bare(_TestPlugin):
            name = "bare"
            version = "0.0.0"
            description = ""

        reg = PluginRegistry()
        p = _TestPlugin()
        b = Bare()
        reg.register(p)
        reg.register(b)
        results = reg.validate_all()
        assert "bare" in results
        assert "test-plugin" not in results  # clean plugin

    # ── Dispatch hooks ─────────────────────────────────────────

    async def test_dispatch_action_pre(self):
        class Modify(_TestPlugin):
            name = "modifier"

            async def on_action_pre(self, action):
                action.tag = "modified"
                return action

        reg = PluginRegistry()
        reg.register(Modify())
        from types import SimpleNamespace

        a = SimpleNamespace()
        result = await reg.dispatch_action_pre(a)
        assert result.tag == "modified"

    async def test_dispatch_swallows_errors(self):
        class Broken(_TestPlugin):
            name = "broken"

            async def on_action_pre(self, action):
                raise RuntimeError("boom")

        reg = PluginRegistry()
        reg.register(Broken())
        from types import SimpleNamespace

        a = SimpleNamespace()
        result = await reg.dispatch_action_pre(a)
        assert result is a  # original returned despite error

    async def test_dispatch_llm_pre(self):
        reg = PluginRegistry()
        reg.register(_TestPlugin())
        msgs = [{"role": "user", "content": "hi"}]
        result = await reg.dispatch_llm_pre(msgs)
        assert result == msgs

    async def test_dispatch_llm_pre_error(self):
        class Broken(_TestPlugin):
            name = "broken-llm-pre"

            async def on_llm_pre(self, messages, **kwargs):
                raise RuntimeError("boom")

        reg = PluginRegistry()
        reg.register(Broken())
        msgs = [{"role": "user", "content": "hi"}]
        result = await reg.dispatch_llm_pre(msgs)
        assert result == msgs

    async def test_dispatch_tool_invoke(self):
        reg = PluginRegistry()
        reg.register(_TestPlugin())
        args = {"a": 1}
        result = await reg.dispatch_tool_invoke("tool", args)
        assert result == args

    async def test_dispatch_action_post(self):
        class Modify(_TestPlugin):
            name = "modifier-post"

            async def on_action_post(self, action, observation):
                observation.tag = "post"
                return observation

        reg = PluginRegistry()
        reg.register(Modify())
        obs = SimpleNamespace()
        result = await reg.dispatch_action_post(SimpleNamespace(), obs)
        assert result.tag == "post"

    async def test_dispatch_action_post_error(self):
        class Broken(_TestPlugin):
            name = "broken-post"

            async def on_action_post(self, action, observation):
                raise RuntimeError("boom")

        reg = PluginRegistry()
        reg.register(Broken())
        obs = SimpleNamespace()
        result = await reg.dispatch_action_post(SimpleNamespace(), obs)
        assert result is obs

    async def test_dispatch_event(self):
        class EventPlugin(_TestPlugin):
            name = "event"

            async def on_event(self, event):
                event.tag = "event"

        reg = PluginRegistry()
        reg.register(EventPlugin())
        evt = SimpleNamespace()
        await reg.dispatch_event(evt)
        assert evt.tag == "event"

    async def test_dispatch_event_error(self):
        class Broken(_TestPlugin):
            name = "broken-event"

            async def on_event(self, event):
                raise RuntimeError("boom")

        reg = PluginRegistry()
        reg.register(Broken())
        await reg.dispatch_event(SimpleNamespace())

    async def test_dispatch_session_hooks(self):
        class SessionPlugin(_TestPlugin):
            name = "session"

            async def on_session_start(self, session_id, metadata):
                metadata["started"] = session_id

            async def on_session_end(self, session_id, metadata):
                metadata["ended"] = session_id

        reg = PluginRegistry()
        reg.register(SessionPlugin())
        meta_start = {"init": True}
        meta_end = {"init": True}
        await reg.dispatch_session_start("s1", meta_start)
        await reg.dispatch_session_end("s1", meta_end)
        assert meta_start["started"] == "s1"
        assert meta_end["ended"] == "s1"

    async def test_dispatch_session_hooks_error(self):
        class Broken(_TestPlugin):
            name = "broken-session"

            async def on_session_start(self, session_id, metadata):
                raise RuntimeError("boom")

            async def on_session_end(self, session_id, metadata):
                raise RuntimeError("boom")

        reg = PluginRegistry()
        reg.register(Broken())
        await reg.dispatch_session_start("s1", {"init": True})
        await reg.dispatch_session_end("s1", {"init": True})

    async def test_dispatch_llm_post(self):
        class LlmPlugin(_TestPlugin):
            name = "llm"

            async def on_llm_post(self, response):
                return {"ok": True}

        reg = PluginRegistry()
        reg.register(LlmPlugin())
        result = await reg.dispatch_llm_post({"ok": False})
        assert result == {"ok": True}

    async def test_dispatch_llm_post_error(self):
        class Broken(_TestPlugin):
            name = "broken-llm"

            async def on_llm_post(self, response):
                raise RuntimeError("boom")

        reg = PluginRegistry()
        reg.register(Broken())
        result = await reg.dispatch_llm_post({"ok": False})
        assert result == {"ok": False}

    async def test_dispatch_condense(self):
        class CondensePlugin(_TestPlugin):
            name = "condense"

            async def on_condense(self, original_events, condensed_events, metadata):
                return condensed_events + ["extra"]

        reg = PluginRegistry()
        reg.register(CondensePlugin())
        result = await reg.dispatch_condense(["a"], ["b"], {})
        assert result == ["b", "extra"]

    async def test_dispatch_condense_error(self):
        class Broken(_TestPlugin):
            name = "broken-condense"

            async def on_condense(self, original_events, condensed_events, metadata):
                raise RuntimeError("boom")

        reg = PluginRegistry()
        reg.register(Broken())
        result = await reg.dispatch_condense(["a"], ["b"], {})
        assert result == ["b"]

    async def test_dispatch_memory_recall(self):
        class MemoryPlugin(_TestPlugin):
            name = "memory"

            async def on_memory_recall(self, recall_type, content):
                content["recall_type"] = recall_type
                return content

        reg = PluginRegistry()
        reg.register(MemoryPlugin())
        result = await reg.dispatch_memory_recall("knowledge", {"x": 1})
        assert result["recall_type"] == "knowledge"

    async def test_dispatch_memory_recall_error(self):
        class Broken(_TestPlugin):
            name = "broken-memory"

            async def on_memory_recall(self, recall_type, content):
                raise RuntimeError("boom")

        reg = PluginRegistry()
        reg.register(Broken())
        result = await reg.dispatch_memory_recall("knowledge", {"x": 1})
        assert result == {"x": 1}

    async def test_dispatch_tool_invoke_error(self):
        class Broken(_TestPlugin):
            name = "broken-tool"

            async def on_tool_invoke(self, tool_name, tool_args):
                raise RuntimeError("boom")

        reg = PluginRegistry()
        reg.register(Broken())
        result = await reg.dispatch_tool_invoke("tool", {"x": 1})
        assert result == {"x": 1}

    def test_validate_all_handles_errors(self):
        class Broken(_TestPlugin):
            name = "broken"

            def validate(self):
                raise RuntimeError("boom")

        reg = PluginRegistry()
        reg.register(Broken())
        results = reg.validate_all()
        assert "broken" in results


class TestDiscovery:
    def test_discover_plugins_select(self, monkeypatch):
        reg = PluginRegistry()

        class DummyEP:
            def __init__(self, name, func):
                self.name = name
                self._func = func

            def load(self):
                return self._func

        def register_fn(r):
            r.register(_TestPlugin())

        class EPs:
            def select(self, group):
                if group == "forge.plugins":
                    return [DummyEP("ok", register_fn)]
                return []

        monkeypatch.setattr("importlib.metadata.entry_points", lambda: EPs())

        discover_plugins(reg)
        assert reg.get_plugin("test-plugin") is not None

    def test_discover_plugins_fallback_group(self, monkeypatch):
        reg = PluginRegistry()

        class DummyEP:
            def __init__(self, name, func):
                self.name = name
                self._func = func

            def load(self):
                return self._func

        def register_fn(r):
            r.register(_TestPlugin())

        def entry_points(*_args, **kwargs):
            if "group" in kwargs:
                return [DummyEP("ok", register_fn)]
            return []

        monkeypatch.setattr("importlib.metadata.entry_points", entry_points)

        discover_plugins(reg)
        assert reg.get_plugin("test-plugin") is not None

    def test_discover_plugins_non_callable_and_error(self, monkeypatch):
        reg = PluginRegistry()

        class DummyEP:
            def __init__(self, name, func):
                self.name = name
                self._func = func

            def load(self):
                if self._func is None:
                    raise RuntimeError("boom")
                return self._func

        def entry_points(*_args, **kwargs):
            if "group" in kwargs:
                return [DummyEP("bad", "not-callable"), DummyEP("err", None)]
            return []

        monkeypatch.setattr("importlib.metadata.entry_points", entry_points)

        discover_plugins(reg)
        assert reg.get_plugin("test-plugin") is None

    def test_get_plugin_registry_cached(self):
        with patch("backend.core.plugin.discover_plugins") as discover:
            discover.return_value = PluginRegistry()
            get_plugin_registry.cache_clear()
            reg1 = get_plugin_registry()
            reg2 = get_plugin_registry()
        assert reg1 is reg2

    def test_discover_plugins_creates_registry(self, monkeypatch):
        class EPs:
            def select(self, group):
                return []

        monkeypatch.setattr("importlib.metadata.entry_points", lambda: EPs())

        reg = discover_plugins()
        assert isinstance(reg, PluginRegistry)
