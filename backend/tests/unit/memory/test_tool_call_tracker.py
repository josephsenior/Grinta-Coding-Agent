"""Tests for memory tool call tracking utilities."""



from backend.core.message import Message, TextContent, ToolCall, ToolCallFunction
from backend.memory.tool_call_tracker import (
    collect_tool_call_ids,
    collect_tool_response_ids,
    filter_unmatched_tool_calls,
)


class TestCollectToolCallIds:
    def test_empty_messages(self):
        """Test collecting tool call IDs from empty list."""
        result = collect_tool_call_ids([])
        assert result == set()

    def test_assistant_message_with_tool_calls(self):
        """Test collecting IDs from assistant messages."""
        msg = Message(
            role="assistant",
            content=[],
            tool_calls=[
                ToolCall(
                    id="call_1", function=ToolCallFunction(name="search", arguments="{}")
                ),
                ToolCall(
                    id="call_2",
                    function=ToolCallFunction(name="read_file", arguments="{}"),
                ),
            ],
        )
        result = collect_tool_call_ids([msg])
        assert result == {"call_1", "call_2"}

    def test_user_message_tool_calls_ignored(self):
        """Test that tool calls from non-assistant roles are ignored."""
        msg = Message(
            role="user",
            content=[],
            tool_calls=[
                ToolCall(id="call_x", function=ToolCallFunction(name="test", arguments="{}"))
            ],
        )
        result = collect_tool_call_ids([msg])
        assert result == set()

    def test_multiple_assistant_messages(self):
        """Test collecting IDs from multiple assistant messages."""
        messages = [
            Message(
                role="assistant",
                content=[],
                tool_calls=[
                    ToolCall(
                        id="call_1", function=ToolCallFunction(name="search", arguments="{}")
                    )
                ],
            ),
            Message(
                role="assistant",
                content=[],
                tool_calls=[
                    ToolCall(
                        id="call_2", function=ToolCallFunction(name="read", arguments="{}")
                    )
                ],
            ),
        ]
        result = collect_tool_call_ids(messages)
        assert result == {"call_1", "call_2"}

    def test_mixed_messages(self):
        """Test collecting from mix of message types."""
        messages = [
            Message(role="user", content=[TextContent(text="Hello")]),
            Message(
                role="assistant",
                content=[],
                tool_calls=[
                    ToolCall(
                        id="call_1", function=ToolCallFunction(name="search", arguments="{}")
                    )
                ],
            ),
            Message(
                role="tool",
                content=[TextContent(text="result")],
                tool_call_id="call_1",
            ),
        ]
        result = collect_tool_call_ids(messages)
        assert result == {"call_1"}

    def test_no_tool_call_id(self):
        """Test handling tool calls without ID."""
        msg = Message(
            role="assistant",
            content=[],
            tool_calls=[
                ToolCall(id="", function=ToolCallFunction(name="test", arguments="{}"))
            ],
        )
        result = collect_tool_call_ids([msg])
        assert result == set()

    def test_duplicate_ids(self):
        """Test that duplicate IDs are deduplicated."""
        msg = Message(
            role="assistant",
            content=[],
            tool_calls=[
                ToolCall(id="call_1", function=ToolCallFunction(name="test1", arguments="{}")),
                ToolCall(id="call_1", function=ToolCallFunction(name="test2", arguments="{}")),
            ],
        )
        result = collect_tool_call_ids([msg])
        assert result == {"call_1"}


class TestCollectToolResponseIds:
    def test_empty_messages(self):
        """Test collecting response IDs from empty list."""
        result = collect_tool_response_ids([])
        assert result == set()

    def test_tool_message_with_id(self):
        """Test collecting IDs from tool messages."""
        msg = Message(
            role="tool", content=[TextContent(text="result")], tool_call_id="call_1"
        )
        result = collect_tool_response_ids([msg])
        assert result == {"call_1"}

    def test_multiple_tool_messages(self):
        """Test collecting from multiple tool messages."""
        messages = [
            Message(
                role="tool", content=[TextContent(text="result1")], tool_call_id="call_1"
            ),
            Message(
                role="tool", content=[TextContent(text="result2")], tool_call_id="call_2"
            ),
        ]
        result = collect_tool_response_ids(messages)
        assert result == {"call_1", "call_2"}

    def test_non_tool_messages_ignored(self):
        """Test that non-tool messages are ignored."""
        messages = [
            Message(role="user", content=[TextContent(text="test")]),
            Message(role="assistant", content=[TextContent(text="response")]),
        ]
        result = collect_tool_response_ids(messages)
        assert result == set()

    def test_tool_message_without_id(self):
        """Test tool message without tool_call_id."""
        msg = Message(
            role="tool", content=[TextContent(text="result")], tool_call_id=None
        )
        result = collect_tool_response_ids([msg])
        assert result == set()

    def test_mixed_messages(self):
        """Test collecting from mix of message types."""
        messages = [
            Message(role="user", content=[TextContent(text="Hello")]),
            Message(
                role="tool", content=[TextContent(text="result")], tool_call_id="call_1"
            ),
            Message(role="assistant", content=[TextContent(text="OK")]),
        ]
        result = collect_tool_response_ids(messages)
        assert result == {"call_1"}

    def test_duplicate_response_ids(self):
        """Test that duplicate response IDs are deduplicated."""
        messages = [
            Message(
                role="tool", content=[TextContent(text="result1")], tool_call_id="call_1"
            ),
            Message(
                role="tool", content=[TextContent(text="result2")], tool_call_id="call_1"
            ),
        ]
        result = collect_tool_response_ids(messages)
        assert result == {"call_1"}


class TestFilterUnmatchedToolCalls:
    def test_empty_messages(self):
        """Test filtering empty message list."""
        result = list(filter_unmatched_tool_calls([]))
        assert result == []

    def test_matched_tool_call_and_response(self):
        """Test that matched pairs pass through."""
        messages = [
            Message(
                role="assistant",
                content=[],
                tool_calls=[
                    ToolCall(
                        id="call_1", function=ToolCallFunction(name="search", arguments="{}")
                    )
                ],
            ),
            Message(
                role="tool", content=[TextContent(text="result")], tool_call_id="call_1"
            ),
        ]
        result = list(filter_unmatched_tool_calls(messages))
        assert len(result) == 2
        assert result[0].role == "assistant"
        assert result[1].role == "tool"

    def test_unmatched_tool_response_filtered(self):
        """Test that tool responses without matching call are filtered."""
        messages = [
            Message(
                role="tool",
                content=[TextContent(text="orphan result")],
                tool_call_id="call_999",
            ),
        ]
        result = list(filter_unmatched_tool_calls(messages))
        assert result == []

    def test_regular_messages_pass_through(self):
        """Test that non-tool messages pass through unchanged."""
        messages = [
            Message(role="user", content=[TextContent(text="Hello")]),
            Message(role="assistant", content=[TextContent(text="Hi there")]),
        ]
        result = list(filter_unmatched_tool_calls(messages))
        assert len(result) == 2
        assert result[0].content[0].text == "Hello"
        assert result[1].content[0].text == "Hi there"

    def test_partially_matched_tool_calls(self):
        """Test assistant message with multiple tool calls, some matched."""
        messages = [
            Message(
                role="assistant",
                content=[],
                tool_calls=[
                    ToolCall(
                        id="call_1", function=ToolCallFunction(name="search", arguments="{}")
                    ),
                    ToolCall(
                        id="call_2", function=ToolCallFunction(name="read", arguments="{}")
                    ),
                ],
            ),
            Message(
                role="tool", content=[TextContent(text="result")], tool_call_id="call_1"
            ),
            # call_2 has no response
        ]
        result = list(filter_unmatched_tool_calls(messages))
        # Assistant message should be included but trimmed, plus matched tool response
        assert len(result) == 2
        assert result[0].role == "assistant"
        assert result[0].tool_calls is not None
        assert len(result[0].tool_calls) == 1
        assert result[0].tool_calls[0].id == "call_1"

    def test_mixed_scenario(self):
        """Test complex scenario with multiple message types."""
        messages = [
            Message(role="user", content=[TextContent(text="Question")]),
            Message(
                role="assistant",
                content=[],
                tool_calls=[
                    ToolCall(
                        id="call_1", function=ToolCallFunction(name="search", arguments="{}")
                    )
                ],
            ),
            Message(
                role="tool", content=[TextContent(text="result")], tool_call_id="call_1"
            ),
            Message(
                role="assistant", content=[TextContent(text="Answer based on result")]
            ),
        ]
        result = list(filter_unmatched_tool_calls(messages))
        assert len(result) == 4

    def test_all_tool_calls_unmatched(self):
        """Test assistant message with all unmatched tool calls is filtered."""
        messages = [
            Message(
                role="assistant",
                content=[],
                tool_calls=[
                    ToolCall(
                        id="call_1", function=ToolCallFunction(name="search", arguments="{}")
                    ),
                    ToolCall(
                        id="call_2", function=ToolCallFunction(name="read", arguments="{}")
                    ),
                ],
            ),
            # No tool responses
        ]
        result = list(filter_unmatched_tool_calls(messages))
        # Should be filtered out
        assert result == []
