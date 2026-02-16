"""Unit tests for backend.core.plugin — plugin system + registry."""

from __future__ import annotations

import warnings

import pytest

from backend.core.plugin import (
    ForgePlugin,
    HookType,
    PLUGIN_API_VERSION,
    PLUGIN_COMPAT_WINDOW,
    PluginRegistry,
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
        assert len(reg.plugins) == 0

    def test_unregister_missing(self):
        reg = PluginRegistry()
        reg.unregister("nope")  # should not raise

    def test_reject_incompatible_version(self):
        class FuturePlugin(_TestPlugin):
            name = "future"
            min_api_version = (999, 0)

        reg = PluginRegistry()
        reg.register(FuturePlugin())
        assert len(reg.plugins) == 0

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

    async def test_dispatch_tool_invoke(self):
        reg = PluginRegistry()
        reg.register(_TestPlugin())
        args = {"a": 1}
        result = await reg.dispatch_tool_invoke("tool", args)
        assert result == args
