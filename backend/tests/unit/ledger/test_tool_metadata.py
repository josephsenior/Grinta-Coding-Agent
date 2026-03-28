"""Tests for backend.ledger.tool — ToolCallMetadata and helpers."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.ledger.model_response_lite import (
    AssistantMessageLite,
    AssistantToolCallLite,
    ChoiceLite,
    ModelResponseLite,
)
from backend.ledger.tool import ToolCallMetadata, build_tool_call_metadata


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fake_sdk_response(
    resp_id: str = "resp-1",
    model: str = "gpt-4",
    content: str = "Hello",
    tool_call_id: str | None = None,
) -> SimpleNamespace:
    """Build a minimal SDK-like response object."""
    tool_calls = None
    if tool_call_id:
        func = SimpleNamespace(name="do_thing", arguments='{"x":1}')
        tool_calls = [SimpleNamespace(id=tool_call_id, function=func)]
    message = SimpleNamespace(role="assistant", content=content, tool_calls=tool_calls)
    choice = SimpleNamespace(message=message)
    return SimpleNamespace(id=resp_id, model=model, choices=[choice])


# ===================================================================
# ModelResponseLite
# ===================================================================


class TestModelResponseLite:
    def test_from_sdk_with_namespace(self):
        resp = _fake_sdk_response(resp_id="r1", model="gpt-4", content="hi")
        lite = ModelResponseLite.from_sdk(resp)
        assert lite.id == "r1"
        assert lite.model == "gpt-4"
        assert len(lite.choices) == 1
        assert lite.choices[0].message is not None
        assert lite.choices[0].message.content == "hi"
        assert lite.choices[0].message.role == "assistant"

    def test_from_sdk_with_dict(self):
        resp = {
            "id": "d1",
            "model": "claude",
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "text",
                        "tool_calls": None,
                    }
                }
            ],
        }
        lite = ModelResponseLite.from_sdk(resp)
        assert lite.id == "d1"
        assert lite.model == "claude"
        assert len(lite.choices) == 1
        assert lite.choices[0].message is not None
        assert lite.choices[0].message.content == "text"

    def test_from_sdk_no_choices(self):
        resp = SimpleNamespace(id="x", model="m", choices=[])
        lite = ModelResponseLite.from_sdk(resp)
        assert lite.choices == []

    def test_from_sdk_none_choices(self):
        resp = SimpleNamespace(id="x", model="m", choices=None)
        lite = ModelResponseLite.from_sdk(resp)
        assert lite.choices == []

    def test_from_sdk_message_none(self):
        choice = SimpleNamespace(message=None)
        resp = SimpleNamespace(id="a", model="b", choices=[choice])
        lite = ModelResponseLite.from_sdk(resp)
        assert lite.choices[0].message is None

    def test_from_sdk_tool_calls(self):
        resp = _fake_sdk_response(tool_call_id="tc-42")
        lite = ModelResponseLite.from_sdk(resp)
        msg = lite.choices[0].message
        assert msg is not None
        assert msg.tool_calls is not None
        assert len(msg.tool_calls) == 1
        assert msg.tool_calls[0].id == "tc-42"

    def test_get_method(self):
        lite = ModelResponseLite(id="z", model="m", choices=[])
        assert lite.get("id") == "z"
        assert lite.get("nonexistent", "default") == "default"

    def test_model_dump_roundtrip(self):
        resp = _fake_sdk_response(tool_call_id="tc-1")
        lite = ModelResponseLite.from_sdk(resp)
        data = lite.model_dump()
        assert isinstance(data, dict)
        assert data["id"] == "resp-1"
        assert len(data["choices"]) == 1

    def test_getattr_or_get_fallback(self):
        # object with no attribute
        result = ModelResponseLite._getattr_or_get(42, "id", "fallback")
        assert result == "fallback"


# ===================================================================
# AssistantToolCallLite / AssistantMessageLite / ChoiceLite
# ===================================================================


class TestLiteModels:
    def test_tool_call_lite_defaults(self):
        tc = AssistantToolCallLite()
        assert tc.id is None
        assert tc.function is None

    def test_tool_call_lite_with_values(self):
        tc = AssistantToolCallLite(id="call-1", function={"name": "f"})
        assert tc.id == "call-1"

    def test_message_lite_defaults(self):
        msg = AssistantMessageLite()
        assert msg.role is None
        assert msg.content is None
        assert msg.tool_calls is None

    def test_choice_lite_defaults(self):
        ch = ChoiceLite()
        assert ch.message is None


# ===================================================================
# ToolCallMetadata
# ===================================================================


class TestToolCallMetadata:
    def test_from_sdk_basic(self):
        resp = _fake_sdk_response()
        md = ToolCallMetadata.from_sdk(
            function_name="run_cmd",
            tool_call_id="tc-1",
            response_obj=resp,
            total_calls_in_response=1,
        )
        assert md.function_name == "run_cmd"
        assert md.tool_call_id == "tc-1"
        assert md.total_calls_in_response == 1
        assert md.model_response is not None
        assert md._raw_response is resp

    def test_from_sdk_stores_raw_response(self):
        resp = _fake_sdk_response()
        md = ToolCallMetadata.from_sdk(
            function_name="f",
            tool_call_id="t",
            response_obj=resp,
            total_calls_in_response=2,
        )
        assert md._raw_response is resp

    def test_model_response_is_dict(self):
        resp = _fake_sdk_response()
        md = ToolCallMetadata.from_sdk(
            function_name="f",
            tool_call_id="t",
            response_obj=resp,
            total_calls_in_response=1,
        )
        assert isinstance(md.model_response, dict)
        assert "id" in md.model_response

    def test_validation_empty_function_name(self):
        with pytest.raises(Exception):
            ToolCallMetadata(
                function_name="",
                tool_call_id="t",
                model_response=None,
                total_calls_in_response=1,
            )

    def test_validation_empty_tool_call_id(self):
        with pytest.raises(Exception):
            ToolCallMetadata(
                function_name="f",
                tool_call_id="",
                model_response=None,
                total_calls_in_response=1,
            )

    def test_validation_total_calls_zero(self):
        with pytest.raises(Exception):
            ToolCallMetadata(
                function_name="f",
                tool_call_id="t",
                model_response=None,
                total_calls_in_response=0,
            )


# ===================================================================
# build_tool_call_metadata
# ===================================================================


class TestBuildToolCallMetadata:
    def test_returns_tool_call_metadata(self):
        resp = _fake_sdk_response()
        md = build_tool_call_metadata(
            function_name="cmd_run",
            tool_call_id="call-99",
            response_obj=resp,
            total_calls_in_response=3,
        )
        assert isinstance(md, ToolCallMetadata)
        assert md.function_name == "cmd_run"
        assert md.tool_call_id == "call-99"
        assert md.total_calls_in_response == 3

    def test_build_with_dict_response(self):
        resp = {"id": "x", "model": "y", "choices": []}
        md = build_tool_call_metadata(
            function_name="f",
            tool_call_id="t",
            response_obj=resp,
            total_calls_in_response=1,
        )
        assert md.model_response is not None
        assert md._raw_response is resp

    def test_build_with_none_response(self):
        md = build_tool_call_metadata(
            function_name="f",
            tool_call_id="t",
            response_obj=None,
            total_calls_in_response=1,
        )
        assert md._raw_response is None
