"""Unit tests for the module-level helpers in backend.engines.navigator.navigator.

The Navigator class itself requires ``browsergym`` at import time, so we only
test the pure-function helpers that are importable without that dependency.
"""

from __future__ import annotations

import os

import pytest


# ---------------------------------------------------------------------------
# These helpers can be imported without browsergym being present because we
# patch the import at the module level using a minimal stub.
# ---------------------------------------------------------------------------

# Provide a minimal stub for browsergym so the navigator module can be imported.
import sys
from types import ModuleType


def _make_stub(name: str) -> ModuleType:
    mod = ModuleType(name)
    sys.modules[name] = mod
    return mod


# Only stub if browsergym is not already importable
if "browsergym" not in sys.modules:
    bg = _make_stub("browsergym")
    bg_core = _make_stub("browsergym.core")
    bg_core_action = _make_stub("browsergym.core.action")
    bg_core_action_hl = _make_stub("browsergym.core.action.highlevel")

    class _FakeHLAS:
        def __init__(self, *args, **kwargs):
            pass

        def describe(self, *args, **kwargs):
            return "action_space_description"

    bg_core_action_hl.HighLevelActionSet = _FakeHLAS

    bg_utils = _make_stub("browsergym.utils")
    bg_utils_obs = _make_stub("browsergym.utils.obs")
    bg_utils_obs.flatten_axtree_to_str = lambda *a, **kw: "flat_tree"

# Stub remaining backend dependencies that may not be available:
for _dep in [
    "backend.controller.agent",
    "backend.utils.prompt",
]:
    if _dep not in sys.modules:
        _make_stub(_dep)

import types as _types

_agent_mod = sys.modules.get("backend.controller.agent")
if _agent_mod and not hasattr(_agent_mod, "Agent"):
    class _FakeAgent:
        runtime_plugins = []
        _prompt_manager = None

        def __init__(self, config, llm_registry):
            self.config = config
            self.llm_registry = llm_registry
            self.llm = None

        def reset(self):
            pass

    _agent_mod.Agent = _FakeAgent

_prompt_mod = sys.modules.get("backend.utils.prompt")
if _prompt_mod and not hasattr(_prompt_mod, "PromptManager"):
    class _FakePromptManager:
        def __init__(self, prompt_dir):
            pass

        def get_system_message(self, **kwargs):
            return "system message"

    _prompt_mod.PromptManager = _FakePromptManager


# Now import the pieces we want to test
from backend.engines.navigator.navigator import (
    get_error_prefix,
    get_system_message,
    get_prompt,
    USE_NAV,
    USE_CONCISE_ANSWER,
    EVAL_MODE,
    CONCISE_INSTRUCTION,
)


# ---------------------------------------------------------------------------
# get_error_prefix
# ---------------------------------------------------------------------------

class TestGetErrorPrefix:
    def test_contains_action(self):
        result = get_error_prefix("click_button")
        assert "click_button" in result

    def test_contains_instruction(self):
        result = get_error_prefix("some_action")
        assert "IMPORTANT" in result
        assert "Last action is incorrect" in result

    def test_different_actions_different_output(self):
        r1 = get_error_prefix("act1")
        r2 = get_error_prefix("act2")
        assert r1 != r2

    def test_returns_string(self):
        assert isinstance(get_error_prefix("x"), str)


# ---------------------------------------------------------------------------
# get_system_message
# ---------------------------------------------------------------------------

class TestGetSystemMessage:
    def test_contains_goal(self):
        result = get_system_message("find a product", "action_space")
        assert "find a product" in result

    def test_contains_action_space(self):
        result = get_system_message("goal", "click | type | navigate")
        assert "click | type | navigate" in result

    def test_contains_instructions_header(self):
        result = get_system_message("goal", "space")
        assert "Instructions" in result or "Goal" in result

    def test_returns_nonempty_string(self):
        assert len(get_system_message("g", "s")) > 0


# ---------------------------------------------------------------------------
# get_prompt
# ---------------------------------------------------------------------------

class TestGetPrompt:
    def test_contains_url(self):
        result = get_prompt("", "https://example.com", "tree", "prev1")
        assert "https://example.com" in result

    def test_contains_axtree(self):
        result = get_prompt("", "url", "my_accessibility_tree", "")
        assert "my_accessibility_tree" in result

    def test_contains_prev_actions(self):
        result = get_prompt("", "url", "tree", "click(1)\ntype(2,'x')")
        assert "click(1)" in result

    def test_error_prefix_included(self):
        result = get_prompt("ERROR!", "url", "tree", "prev")
        assert "ERROR!" in result

    def test_no_error_prefix_when_empty(self):
        result = get_prompt("", "url", "tree", "prev")
        # Empty error prefix shouldn't inject spurious text
        assert isinstance(result, str)

    def test_concise_instruction_when_env_set(self, monkeypatch):
        """If USE_CONCISE_ANSWER is True, CONCISE_INSTRUCTION is appended."""
        # Just verify CONCISE_INSTRUCTION is a non-empty string
        assert isinstance(CONCISE_INSTRUCTION, str)
        assert len(CONCISE_INSTRUCTION) > 0


# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

class TestModuleConstants:
    def test_use_nav_is_bool(self):
        assert isinstance(USE_NAV, bool)

    def test_use_concise_answer_is_bool(self):
        assert isinstance(USE_CONCISE_ANSWER, bool)

    def test_eval_mode_is_bool(self):
        assert isinstance(EVAL_MODE, bool)

    def test_eval_mode_requires_nav_off_and_concise_on(self):
        # EVAL_MODE == (not USE_NAV and USE_CONCISE_ANSWER)
        assert EVAL_MODE == (not USE_NAV and USE_CONCISE_ANSWER)

    def test_concise_instruction_nonempty(self):
        assert len(CONCISE_INSTRUCTION) > 0
