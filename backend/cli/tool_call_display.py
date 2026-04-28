"""User-facing summaries for LLM tool calls (CLI) — avoid raw JSON in the transcript.

This module is a thin façade over the :mod:`backend.cli._tool_display` package.
The implementation is split into focused submodules
(:mod:`~backend.cli._tool_display.headline`,
:mod:`~backend.cli._tool_display.summarize`,
:mod:`~backend.cli._tool_display.redact`,
:mod:`~backend.cli._tool_display.preview`) so each file stays well under the
1k-LOC ceiling and individual helpers stay below the cyclomatic-complexity
threshold.  All previously public names continue to be importable from
``backend.cli.tool_call_display``.
"""

from __future__ import annotations

from backend.cli._tool_display.headline import (
    friendly_verb_for_tool,
    tool_activity_stats_hint,
    tool_headline,
)
from backend.cli._tool_display.preview import (
    flatten_tool_call_for_history,
    looks_like_streaming_tool_arguments,
    mcp_result_user_preview,
    try_format_message_as_tool_json,
)
from backend.cli._tool_display.redact import (
    extract_tool_calls_from_text_markers,
    redact_internal_result_markers,
    redact_streamed_tool_call_markers,
    redact_task_list_json_blobs,
    strip_protocol_echo_blocks,
    strip_tool_call_marker_lines,
)
from backend.cli._tool_display.summarize import (
    format_tool_activity_rows,
    format_tool_invocation_line,
    parse_tool_arguments_json,
    streaming_args_hint,
    summarize_tool_arguments,
)

__all__ = [
    'extract_tool_calls_from_text_markers',
    'flatten_tool_call_for_history',
    'format_tool_activity_rows',
    'format_tool_invocation_line',
    'friendly_verb_for_tool',
    'looks_like_streaming_tool_arguments',
    'mcp_result_user_preview',
    'parse_tool_arguments_json',
    'redact_internal_result_markers',
    'redact_streamed_tool_call_markers',
    'redact_task_list_json_blobs',
    'streaming_args_hint',
    'strip_protocol_echo_blocks',
    'strip_tool_call_marker_lines',
    'summarize_tool_arguments',
    'tool_activity_stats_hint',
    'tool_headline',
    'try_format_message_as_tool_json',
]
