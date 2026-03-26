"""Tests for shared tool-result line format."""

from __future__ import annotations

from backend.llm.tool_result_format import (
    decode_tool_result_payload,
    encode_tool_result_payload,
)


def test_round_trip_decode_payload() -> None:
    name = "execute_bash"
    text = encode_tool_result_payload(name, "hello\nworld")
    decoded = decode_tool_result_payload(text)
    assert decoded is not None
    tool_name, content = decoded
    assert tool_name == name
    assert "hello" in str(content)


def test_decode_tolerates_outer_spacing() -> None:
    text = (
        "  <forge_tool_result_json> "
        "{\"tool_name\":\"my_tool\",\"content\":\"some output\"}"
        " </forge_tool_result_json>  "
    )
    decoded = decode_tool_result_payload(text)
    assert decoded is not None
    assert decoded[0] == "my_tool"


def test_decode_rejects_malformed_payload() -> None:
    text = "<forge_tool_result_json>{\"tool_name\":\"my_tool\",\"content\":}</forge_tool_result_json>"
    assert decode_tool_result_payload(text) is None
