"""Gemini-specific LLM data adapters and mappers."""

from typing import Any
import json


def convert_messages(
    messages: list[dict[str, Any]],
) -> tuple[str | None, list[dict[str, Any]], bool]:
    """Convert messages to Gemini format, extracting system instruction.

    Returns:
        (system_instruction_or_None, gemini_history_messages, caching_requested)
    """
    system_instruction: str | None = None
    gemini_messages: list[dict[str, Any]] = []
    caching_requested = False

    for m in messages:
        content = m.get("content", "")

        # Handle list-style content (from Forge's message serialization)
        text_parts = []
        if isinstance(content, list):
            for item in content:
                if item.get("type") == "text":
                    text_parts.append(item.get("text", ""))
                    if item.get("cache_prompt"):
                        caching_requested = True
                # Image support for Gemini could be added here
            content = "\n".join(text_parts)

        if m["role"] == "system":
            if system_instruction:
                system_instruction += "\n\n" + content
            else:
                system_instruction = content
            continue

        role_name = m.get("role", "user")
        role = "model" if role_name == "assistant" else "user"
        gemini_messages.append({"role": role, "parts": [{"text": content}]})

    return system_instruction, gemini_messages, caching_requested


_GEMINI_ALLOWED_SCHEMA_KEYS = {
    "defs", "maxLength", "default", "minimum", "max_length", "format", 
    "propertyOrdering", "max_items", "min_items", "title", "min_length", 
    "items", "max_properties", "description", "maxProperties", "any_of", 
    "anyOf", "nullable", "property_ordering", "min_properties", "minLength", 
    "example", "enum", "type", "pattern", "minProperties", "required", 
    "minItems", "ref", "properties", "maxItems", "maximum"
}

def _strip_unsupported_schema_fields(schema: Any) -> Any:
    """Recursively strip fields like 'additional_properties' that Gemini rejects."""
    if not isinstance(schema, dict):
        if isinstance(schema, list):
            return [_strip_unsupported_schema_fields(item) for item in schema]
        return schema

    cleaned = {}
    for k, v in schema.items():
        if k not in _GEMINI_ALLOWED_SCHEMA_KEYS:
            continue
            
        if k in ("properties", "defs") and isinstance(v, dict):
            cleaned[k] = {pk: _strip_unsupported_schema_fields(pv) for pk, pv in v.items()}
        elif k in ("required", "enum", "default", "example"):
            cleaned[k] = v
        else:
            cleaned[k] = _strip_unsupported_schema_fields(v)
    return cleaned


def map_tools_to_gemini(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Map OpenAI-style tool definitions to Gemini function_declarations format."""
    gemini_tools = []
    function_declarations = []

    for tool in tools:
        if tool.get("type") == "function" and "function" in tool:
            fn = tool["function"]
            decl = {
                "name": fn["name"],
                "description": fn["description"],
            }
            if "parameters" in fn:
                params = _strip_unsupported_schema_fields(fn["parameters"])
                decl["parameters"] = params
            function_declarations.append(decl)

    if function_declarations:
        gemini_tools.append({"function_declarations": function_declarations})

    return gemini_tools


def extract_generation_config(
    kwargs: dict[str, Any],
) -> tuple[str, dict[str, Any], list | None]:
    """Pop generation-config keys from *kwargs* and return (model_name, gen_config, tools)."""
    model_name = kwargs.pop("model", "")
    if "/" in model_name:
        model_name = model_name.split("/")[-1]

    tools_raw = kwargs.pop("tools", None)
    tools = map_tools_to_gemini(tools_raw) if tools_raw else None

    gen_cfg: dict[str, Any] = {}
    for src, dst in [
        ("temperature", "temperature"),
        ("top_p", "top_p"),
        ("top_k", "top_k"),
        ("max_tokens", "max_output_tokens"),
        ("stop", "stop_sequences"),
    ]:
        if src in kwargs:
            gen_cfg[dst] = kwargs.pop(src)
    # Native Gemini SDK (ChatSession.send_message) does not support tool_choice.
    kwargs.pop("tool_choice", None)
    # Strip OpenAI/liteLLM-style passthrough fields unsupported by Gemini SDK.
    for unsupported_key in (
        "extra_body",
        "extra_headers",
        "response_format",
        "frequency_penalty",
        "presence_penalty",
        "logit_bias",
        "seed",
        "user",
        "reasoning_effort",
        "reasoning",
        "parallel_tool_calls",
        "metadata",
        "stream",
        "stream_options",
        "logprobs",
        "top_logprobs",
        "n",
    ):
        kwargs.pop(unsupported_key, None)
    return model_name, gen_cfg, tools


def gemini_response_to_dict(response: Any) -> dict[str, Any] | None:
    """Best-effort conversion of Gemini SDK response to dict for stable parsing."""
    if isinstance(response, dict):
        return response

    to_dict = getattr(response, "to_dict", None)
    if callable(to_dict):
        try:
            result = to_dict()
            return result if isinstance(result, dict) else None
        except Exception:
            return None
    return None


def iter_candidate_parts(response: Any) -> list[Any]:
    """Return all candidate parts from a Gemini response across SDK shapes."""
    parts: list[Any] = []

    response_dict = gemini_response_to_dict(response)
    if response_dict:
        for candidate in response_dict.get("candidates", []) or []:
            if not isinstance(candidate, dict):
                continue
            content = candidate.get("content", {})
            if not isinstance(content, dict):
                continue
            candidate_parts = content.get("parts")
            if candidate_parts:
                parts.extend(candidate_parts)

    if parts:
        return parts

    for candidate in getattr(response, "candidates", []) or []:
        content = getattr(candidate, "content", None)
        if content is None and isinstance(candidate, dict):
            content = candidate.get("content")

        candidate_parts = None
        if isinstance(content, dict):
            candidate_parts = content.get("parts")
        elif content is not None:
            candidate_parts = getattr(content, "parts", None)

        if candidate_parts:
            parts.extend(candidate_parts)
    return parts


def coerce_fc_name_and_args(function_call: Any) -> tuple[str | None, Any]:
    """Extract function-call name and args from object/dict Gemini shapes."""
    if function_call is None:
        return None, None

    if isinstance(function_call, dict):
        return function_call.get("name"), function_call.get("args")

    return getattr(function_call, "name", None), getattr(function_call, "args", None)


def extract_tool_calls(response: Any) -> list[dict[str, Any]] | None:
    """Extract function call parts from a Gemini response."""
    tool_calls: list[dict[str, Any]] = []
    for part in iter_candidate_parts(response):
        fc = getattr(part, "function_call", None)
        if fc is None and isinstance(part, dict):
            fc = part.get("function_call") or part.get("functionCall")

        name, args = coerce_fc_name_and_args(fc)
        if not name:
            continue

        args_dict: dict[str, Any]
        if args is None:
            args_dict = {}
        elif isinstance(args, dict):
            args_dict = args
        else:
            try:
                args_dict = dict(args)
            except Exception:
                args_dict = {}

        tool_calls.append(
            {
                "id": f"gemini-{len(tool_calls)}",
                "type": "function",
                "function": {
                    "name": name,
                    "arguments": json.dumps(args_dict),
                },
            }
        )

    return tool_calls if tool_calls else None


def extract_text(response: Any) -> str:
    text_parts: list[str] = []
    for part in iter_candidate_parts(response):
        text = getattr(part, "text", None)
        if text is None and isinstance(part, dict):
            text = part.get("text")
        if isinstance(text, str):
            if text.strip():
                text_parts.append(text)

    if text_parts:
        return "\n".join(text_parts)

    response_text = getattr(response, "text", "")
    return response_text if isinstance(response_text, str) else str(response_text or "")


def extract_finish_reason(response: Any) -> str:
    response_dict = gemini_response_to_dict(response)
    if isinstance(response_dict, dict):
        candidates = response_dict.get("candidates") or []
        if candidates and isinstance(candidates[0], dict):
            reason = candidates[0].get("finishReason")
            if isinstance(reason, str) and reason:
                return reason

    for candidate in getattr(response, "candidates", []) or []:
        reason = getattr(candidate, "finish_reason", None)
        if isinstance(reason, str) and reason:
            return reason
        if isinstance(candidate, dict):
            reason = candidate.get("finish_reason") or candidate.get("finishReason")
            if isinstance(reason, str) and reason:
                return reason
    return ""


def extract_block_reason(response: Any) -> str:
    response_dict = gemini_response_to_dict(response)
    if isinstance(response_dict, dict):
        prompt_feedback = response_dict.get("promptFeedback") or response_dict.get(
            "prompt_feedback"
        )
        if isinstance(prompt_feedback, dict):
            reason = prompt_feedback.get("blockReason") or prompt_feedback.get(
                "block_reason"
            )
            if isinstance(reason, str) and reason:
                return reason

    feedback = getattr(response, "prompt_feedback", None)
    if feedback is None:
        feedback = getattr(response, "promptFeedback", None)
    reason = getattr(feedback, "block_reason", None)
    if reason is None:
        reason = getattr(feedback, "blockReason", None)
    return reason if isinstance(reason, str) else ""


def synthesize_empty_text(response: Any) -> str:
    block_reason = extract_block_reason(response)
    if block_reason:
        return (
            "I couldn’t provide a response because this request was blocked by safety "
            "filters. Please rephrase and try again."
        )

    finish_reason = extract_finish_reason(response).upper()
    if finish_reason in {"SAFETY", "RECITATION", "BLOCKLIST"}:
        return (
            "I couldn’t provide a response for this request. Please try a clearer "
            "or safer phrasing and I’ll help."
        )

    return (
        "I couldn’t generate a complete response this turn. Please resend your "
        "request and I’ll answer directly."
    )


def ensure_non_empty_content(
    response: Any, content: str, tool_calls: list[dict[str, Any]] | None
) -> str:
    if content.strip() or tool_calls:
        return content
    return synthesize_empty_text(response)


def gemini_usage(response: Any) -> dict[str, int]:
    try:
        if hasattr(response, "usage_metadata"):
            usage = response.usage_metadata
            return {
                "prompt_tokens": getattr(usage, "prompt_token_count", 0),
                "completion_tokens": getattr(usage, "candidates_token_count", 0),
                "total_tokens": getattr(usage, "total_token_count", 0),
            }

        response_dict = gemini_response_to_dict(response)
        if response_dict and "usageMetadata" in response_dict:
            usage = response_dict["usageMetadata"]
            return {
                "prompt_tokens": usage.get("promptTokenCount", 0),
                "completion_tokens": usage.get("candidatesTokenCount", 0),
                "total_tokens": usage.get("totalTokenCount", 0),
            }

    except Exception:
        pass
    return {}
