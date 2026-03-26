#!/usr/bin/env python3
"""
Reproduction script to demonstrate how invalid JSON in tool call arguments
flows through _normalize_tool_calls and parse_tool_call_arguments functions.
"""

import json
import traceback
from typing import Any


class FunctionCallValidationError(Exception):
    """Raised when an LLM response fails validation for function calling."""


def _normalize_tool_calls(tool_calls, ):
    if not tool_calls:
        return None
    normalized = []
    for i, tc in enumerate(tool_calls):
        func = tc.get("function", {})
        args = func.get("arguments", "{}")
        if isinstance(args, dict):
            args_str = json.dumps(args)
        elif isinstance(args, str):
            try:
                json.loads(args)
                args_str = args
            except json.JSONDecodeError:
                args_str = "{}" if not args.strip() else args
        elif args is None:
            args_str = "{}"
        else:
            try:
                args_str = str(args)
                json.loads(args_str)
            except Exception:
                args_str = "{}"
        normalized_tc = {
            "id": tc.get("id", f"call_{i}"),
            "type": tc.get("type", "function"),
            "function": {
                "name": str(func.get("name", "")),
                "arguments": args_str,
            }
        }
        normalized.append(normalized_tc)
    return normalized


def parse_tool_call_arguments(tool_call):
    try:
        if isinstance(tool_call.function.arguments, dict):
            return tool_call.function.arguments
        return json.loads(tool_call.function.arguments)
    except (json.JSONDecodeError, AttributeError) as e:
        msg = f"Failed to parse tool call arguments: {e}. Raw arguments: {tool_call.function.arguments}"
        raise FunctionCallValidationError(msg) from e


class ToolCallObject:
    def __init__(self, name, arguments, call_id="call_0"):
        self.function = type('obj', (object,), {'name': name, 'arguments': arguments})()
        self.id = call_id


def main():
    print("=" * 80)
    print("REPRODUCTION: Invalid JSON through Tool Call Functions")
    print("=" * 80)
    print()
    print("STEP 1: Create tool call dict with INVALID JSON arguments")
    print("-" * 80)
    invalid_tool_call = {
        "id": "call_0",
        "type": "function",
        "function": {
            "name": "execute_code",
            "arguments": "not_json"
        }
    }
    print("Input tool call dict:")
    print(json.dumps(invalid_tool_call, indent=2))
    print()
    print("STEP 2: Run through _normalize_tool_calls()")
    print("-" * 80)
    print("Normalizing tool calls...")
    normalized_result = _normalize_tool_calls([invalid_tool_call])
    print("Result from _normalize_tool_calls():")
    print(json.dumps(normalized_result, indent=2))
    print()
    normalized_tc = normalized_result[0]
    print(f"Notice: The invalid JSON 'not_json' is preserved as-is:")
    print(f"  arguments = {repr(normalized_tc['function']['arguments'])}")
    print()
    print("STEP 3: Run normalized result through parse_tool_call_arguments()")
    print("-" * 80)
    tool_call_obj = ToolCallObject(
        name=normalized_tc['function']['name'],
        arguments=normalized_tc['function']['arguments'],
        call_id=normalized_tc['id']
    )
    print("Attempting to parse arguments...")
    try:
        parsed_args = parse_tool_call_arguments(tool_call_obj)
        print(f"Unexpectedly succeeded! Parsed args: {parsed_args}")
    except FunctionCallValidationError as e:
        print("CAUGHT FunctionCallValidationError (Expected!)")
        print(f"\nException Message:")
        print(f"  {str(e)}")
        print(f"\nFull Traceback:")
        print("-" * 80)
        traceback.print_exc()
        print("-" * 80)
    except Exception as e:
        print(f"Unexpected exception type: {type(e).__name__}")
        print(f"  {str(e)}")
        traceback.print_exc()
    print()
    print("=" * 80)
    print("CONCLUSION:")
    print("=" * 80)
    print("The flow demonstrates:")
    print("1. _normalize_tool_calls preserves invalid JSON as-is (can't validate yet)")
    print("2. parse_tool_call_arguments later FAILS when trying to parse the invalid JSON")
    print("3. This ensures validation happens at the right layer (parsing layer)")
    print("=" * 80)


if __name__ == "__main__":
    main()