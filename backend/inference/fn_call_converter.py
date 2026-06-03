"""Slim main file for fn_call_converter.

This file re-exports the public API that other modules and tests import.
The actual implementation is split across 3 dedicated modules:

  - backend.inference._fn_call_examples: telemetry, example building,
    ExampleStepBuilder class, retry-guard helpers, regex constants.
  - backend.inference._fn_call_convert: tool call conversion (XML/JSON
    formatting, validation, parsing) and tool descriptions.
  - backend.inference._fn_call_to_messages: fncall<->non-fncall message
    conversion routines.

The split was a pure code motion — bytes of logic stay identical to the
pre-split `fn_call_converter.py`. All public symbols remain importable
from this module.
"""

from __future__ import annotations

from backend.inference._fn_call_examples import (  # noqa: F401
    IN_CONTEXT_LEARNING_EXAMPLE_PREFIX,
    IN_CONTEXT_LEARNING_EXAMPLE_SUFFIX,
    STOP_WORDS,
    SYSTEM_PROMPT_SUFFIX_TEMPLATE,
    TOOL_EXAMPLES,
    ExampleStepBuilder,
    _FN_CALL_PARSE_COUNTER_KEYS,
    _MALFORMED_PAYLOAD_REJECTION,
    _RETRY_GUARD,
    _RETRY_GUARD_LOCK,
    _RETRY_GUARD_MAX_ENTRIES,
    _STRICT_PARSE_FAILURE,
    _STRICT_PARSE_SUCCESS,
    _XML_TRAILING_TEXT,
    _adapt_example_commands_to_terminal,
    _build_example_footer,
    _build_example_header,
    _build_example_steps,
    _check_retry_guard,
    _compute_content_hash,
    _extract_available_tools,
    _fn_call_parse_counters,
    _fn_call_parse_counters_lock,
    _get_tool_name_mapping,
    _increment_parse_counter,
    _log_xml_parser_diagnostics,
    get_example_for_tools,
    get_fn_call_parse_telemetry_counters,
    reset_fn_call_parse_telemetry_counters,
)
from backend.inference._fn_call_convert import (  # noqa: F401
    _add_example_to_list_content,
    _add_in_context_learning_example,
    _format_parameter,
    _format_tool_call_string,
    _parse_tool_call_arguments,
    _process_system_message,
    _process_user_message,
    _validate_tool_call_structure,
    convert_tool_call_to_string,
    convert_tools_to_description,
)
from backend.inference._fn_call_to_messages import (  # noqa: F401
    _FN_CLOSE_RE,
    _FN_OPEN_RE,
    _PARAM_BLOCK_RE,
    _PARAM_OPEN_HAS_RE,
    _convert_assistant_message,
    _convert_parameter_value,
    _convert_single_message,
    _convert_to_array,
    _convert_to_integer,
    _convert_tool_message,
    _create_tool_call,
    _extract_and_validate_params,
    _extract_parameter_schema,
    _extract_structured_tool_result,
    _extract_tool_call_info,
    _find_matching_tool,
    _find_tool_call_match,
    _find_tool_result_match,
    _fix_stopword,
    _format_tool_content,
    _iter_parameter_matches,
    _looks_like_tool_result_candidate,
    _parse_function_call_from_text,
    _process_assistant_message,
    _process_assistant_message_for_conversion,
    _process_other_message,
    _process_system_message_reverse,
    _process_tool_message,
    _process_user_message_reverse,
    _raise_unexpected_content_type,
    _remove_examples_from_list,
    _remove_examples_from_string,
    _remove_in_context_learning_examples,
    _trim_content_before_function,
    _trim_system_prompt_suffix,
    _validate_enum_constraint,
    _validate_parameter_allowed,
    _validate_required_parameters,
    convert_fncall_messages_to_non_fncall_messages,
    convert_from_multiple_tool_calls_to_single_tool_call_messages,
    convert_non_fncall_messages_to_fncall_messages,
)
