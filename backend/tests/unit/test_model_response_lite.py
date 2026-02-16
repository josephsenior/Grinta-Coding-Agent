"""Tests for backend.events.model_response_lite — lightweight SDK response model."""

from types import SimpleNamespace

import pytest

from backend.events.model_response_lite import (
    AssistantMessageLite,
    AssistantToolCallLite,
    ChoiceLite,
    ModelResponseLite,
)


# ── AssistantToolCallLite ────────────────────────────────────────────

class TestAssistantToolCallLite:
    def test_defaults(self):
        tc = AssistantToolCallLite()
        assert tc.id is None
        assert tc.function is None

    def test_explicit_values(self):
        tc = AssistantToolCallLite(id="tc_1", function={"name": "foo"})
        assert tc.id == "tc_1"
        assert tc.function == {"name": "foo"}


# ── AssistantMessageLite ─────────────────────────────────────────────

class TestAssistantMessageLite:
    def test_defaults(self):
        msg = AssistantMessageLite()
        assert msg.role is None
        assert msg.content is None
        assert msg.tool_calls is None

    def test_with_tool_calls(self):
        tc = AssistantToolCallLite(id="tc_a")
        msg = AssistantMessageLite(role="assistant", content="hi", tool_calls=[tc])
        assert msg.role == "assistant"
        assert msg.content == "hi"
        assert len(msg.tool_calls) == 1
        assert msg.tool_calls[0].id == "tc_a"


# ── ChoiceLite ───────────────────────────────────────────────────────

class TestChoiceLite:
    def test_default_message_none(self):
        c = ChoiceLite()
        assert c.message is None

    def test_with_message(self):
        msg = AssistantMessageLite(role="assistant")
        c = ChoiceLite(message=msg)
        assert c.message.role == "assistant"


# ── ModelResponseLite ────────────────────────────────────────────────

class TestModelResponseLite:
    def test_defaults(self):
        r = ModelResponseLite()
        assert r.id is None
        assert r.model is None
        assert r.choices == []

    def test_get_method(self):
        r = ModelResponseLite(id="resp_1", model="gpt-4")
        assert r.get("id") == "resp_1"
        assert r.get("model") == "gpt-4"
        assert r.get("nonexistent", "default") == "default"

    # ── from_sdk ───────────────────────────────────────────────────

    def test_from_sdk_with_dict(self):
        """from_sdk should work with a plain dict resembling OpenAI response."""
        raw = {
            "id": "chatcmpl-abc",
            "model": "gpt-4",
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "Hello!",
                        "tool_calls": None,
                    }
                }
            ],
        }
        lite = ModelResponseLite.from_sdk(raw)
        assert lite.id == "chatcmpl-abc"
        assert lite.model == "gpt-4"
        assert len(lite.choices) == 1
        assert lite.choices[0].message.content == "Hello!"
        assert lite.choices[0].message.role == "assistant"
        assert lite.choices[0].message.tool_calls is None

    def test_from_sdk_with_namespace_objects(self):
        """from_sdk should work with attribute-based objects (like SDK classes)."""
        tc = SimpleNamespace(id="tc_1", function=SimpleNamespace(name="my_func"))
        msg = SimpleNamespace(
            role="assistant",
            content="thinking",
            tool_calls=[tc],
        )
        choice = SimpleNamespace(message=msg)
        resp = SimpleNamespace(id="resp_42", model="claude", choices=[choice])

        lite = ModelResponseLite.from_sdk(resp)
        assert lite.id == "resp_42"
        assert lite.model == "claude"
        assert len(lite.choices) == 1
        assert lite.choices[0].message.tool_calls is not None
        assert len(lite.choices[0].message.tool_calls) == 1
        assert lite.choices[0].message.tool_calls[0].id == "tc_1"

    def test_from_sdk_empty_choices(self):
        resp = SimpleNamespace(id="r1", model="m1", choices=[])
        lite = ModelResponseLite.from_sdk(resp)
        assert lite.choices == []

    def test_from_sdk_choice_with_no_message(self):
        choice = SimpleNamespace(message=None)
        resp = SimpleNamespace(id="r2", model="m2", choices=[choice])
        lite = ModelResponseLite.from_sdk(resp)
        assert len(lite.choices) == 1
        assert lite.choices[0].message is None

    def test_from_sdk_none_response(self):
        """from_sdk with None should return empty ModelResponseLite."""
        lite = ModelResponseLite.from_sdk(None)
        assert lite.id is None
        assert lite.model is None
        assert lite.choices == []

    def test_from_sdk_no_choices_key(self):
        """from_sdk with object missing choices should default to empty."""
        resp = SimpleNamespace(id="r3", model="m3")
        lite = ModelResponseLite.from_sdk(resp)
        assert lite.choices == []

    def test_from_sdk_tool_calls_not_list(self):
        """tool_calls that is not a list should be treated as None."""
        msg = SimpleNamespace(role="assistant", content="x", tool_calls="not_a_list")
        choice = SimpleNamespace(message=msg)
        resp = SimpleNamespace(id="r4", model="m4", choices=[choice])
        lite = ModelResponseLite.from_sdk(resp)
        assert lite.choices[0].message.tool_calls is None

    def test_model_dump_roundtrip(self):
        """Serialization via model_dump should preserve structure."""
        lite = ModelResponseLite(
            id="r5",
            model="m5",
            choices=[
                ChoiceLite(
                    message=AssistantMessageLite(
                        role="assistant",
                        content="hi",
                        tool_calls=[AssistantToolCallLite(id="tc1")],
                    )
                )
            ],
        )
        data = lite.model_dump()
        assert data["id"] == "r5"
        assert data["choices"][0]["message"]["tool_calls"][0]["id"] == "tc1"

    def test_getattr_or_get_dict_fallback(self):
        """_getattr_or_get should fall back to dict.get(...)."""
        d = {"foo": "bar"}
        assert ModelResponseLite._getattr_or_get(d, "foo") == "bar"
        assert ModelResponseLite._getattr_or_get(d, "missing", 42) == 42

    def test_getattr_or_get_attr_takes_precedence(self):
        ns = SimpleNamespace(foo="attr_val")
        assert ModelResponseLite._getattr_or_get(ns, "foo") == "attr_val"

    def test_getattr_or_get_neither(self):
        """If object has neither attr nor is dict, return default."""
        assert ModelResponseLite._getattr_or_get(12345, "foo", "def") == "def"
