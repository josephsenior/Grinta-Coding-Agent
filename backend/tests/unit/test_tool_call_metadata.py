"""Tests for backend.events.tool — ToolCallMetadata and build_tool_call_metadata."""

from types import SimpleNamespace

import pytest

from backend.events.tool import ToolCallMetadata, build_tool_call_metadata


class TestBuildToolCallMetadata:
    """Tests for the build_tool_call_metadata helper."""

    def test_basic_construction(self):
        resp = SimpleNamespace(
            id="resp_1",
            model="gpt-4",
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        role="assistant",
                        content=None,
                        tool_calls=[
                            SimpleNamespace(
                                id="tc_1",
                                function=SimpleNamespace(name="my_tool"),
                            )
                        ],
                    )
                )
            ],
        )
        meta = build_tool_call_metadata(
            function_name="my_tool",
            tool_call_id="tc_1",
            response_obj=resp,
            total_calls_in_response=1,
        )
        assert isinstance(meta, ToolCallMetadata)
        assert meta.function_name == "my_tool"
        assert meta.tool_call_id == "tc_1"
        assert meta.total_calls_in_response == 1

    def test_with_none_response(self):
        meta = build_tool_call_metadata(
            function_name="fn",
            tool_call_id="tc_2",
            response_obj=None,
            total_calls_in_response=1,
        )
        assert meta.function_name == "fn"
        assert meta.model_response is not None  # Still has a ModelResponseLite dict

    def test_total_calls(self):
        meta = build_tool_call_metadata(
            function_name="f",
            tool_call_id="t",
            response_obj={},
            total_calls_in_response=5,
        )
        assert meta.total_calls_in_response == 5


class TestToolCallMetadata:
    """Tests for ToolCallMetadata model."""

    def test_from_sdk_stores_raw_response(self):
        raw_resp = {"id": "resp_x", "model": "m", "choices": []}
        meta = ToolCallMetadata.from_sdk(
            function_name="read_file",
            tool_call_id="tc_abc",
            response_obj=raw_resp,
            total_calls_in_response=2,
        )
        assert meta._raw_response is raw_resp
        assert meta.function_name == "read_file"
        assert meta.tool_call_id == "tc_abc"
        assert meta.total_calls_in_response == 2

    def test_model_response_is_dict(self):
        resp = SimpleNamespace(id="r1", model="gpt-4", choices=[])
        meta = ToolCallMetadata.from_sdk(
            function_name="fn",
            tool_call_id="tc_1",
            response_obj=resp,
            total_calls_in_response=1,
        )
        # model_response should be a dict (from ModelResponseLite.model_dump())
        assert isinstance(meta.model_response, dict)
        assert meta.model_response["id"] == "r1"
        assert meta.model_response["model"] == "gpt-4"

    def test_from_sdk_with_complex_tool_calls(self):
        tc1 = SimpleNamespace(id="tc_1", function=SimpleNamespace(name="search"))
        tc2 = SimpleNamespace(id="tc_2", function=SimpleNamespace(name="write"))
        msg = SimpleNamespace(
            role="assistant", content=None, tool_calls=[tc1, tc2]
        )
        choice = SimpleNamespace(message=msg)
        resp = SimpleNamespace(id="r2", model="claude", choices=[choice])

        meta = ToolCallMetadata.from_sdk(
            function_name="search",
            tool_call_id="tc_1",
            response_obj=resp,
            total_calls_in_response=2,
        )
        assert meta.total_calls_in_response == 2
        # Verify model_response preserved both tool calls
        choices = meta.model_response.get("choices", [])
        assert len(choices) == 1
        tool_calls = choices[0]["message"]["tool_calls"]
        assert len(tool_calls) == 2
        assert tool_calls[0]["id"] == "tc_1"
        assert tool_calls[1]["id"] == "tc_2"

    def test_serialization_preserves_fields(self):
        meta = ToolCallMetadata.from_sdk(
            function_name="execute",
            tool_call_id="tc_99",
            response_obj=None,
            total_calls_in_response=1,
        )
        data = meta.model_dump()
        assert data["function_name"] == "execute"
        assert data["tool_call_id"] == "tc_99"
        assert data["total_calls_in_response"] == 1
        # _raw_response is a PrivateAttr, should NOT appear in model_dump
        assert "_raw_response" not in data
