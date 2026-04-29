"""Gemini-specific LLM data adapters and mappers."""

import json
from typing import Any


def _build_gemini_model_parts(
    text: str, tool_calls: list[dict[str, Any]] | None
) -> list[dict[str, Any]]:
    """Build a Gemini ``parts`` list for a model turn that issued tool calls.

    Each tool call becomes a ``function_call`` part.  When a tool call carries
    a ``thought_signature`` (Gemini 2.5 thinking models), it is attached to
    the same part so the API accepts the replay on the next turn.  An optional
    leading text part captures the assistant's free-form prelude, if any.
    """
    parts: list[dict[str, Any]] = []
    if text and text.strip():
        parts.append({'text': text})
    for tc in tool_calls or ():
        fn = tc.get('function') or {}
        name = fn.get('name', '')
        args_raw = fn.get('arguments', '{}')
        try:
            args = json.loads(args_raw) if isinstance(args_raw, str) else args_raw
        except Exception:
            args = {}
        if not isinstance(args, dict):
            args = {}
        part: dict[str, Any] = {'function_call': {'name': name, 'args': args}}
        sig = tc.get('thought_signature')
        if isinstance(sig, (bytes, bytearray)):
            part['thought_signature'] = bytes(sig)
        parts.append(part)
    return parts


def _build_gemini_tool_response_parts(
    name: str, content: Any
) -> list[dict[str, Any]]:
    """Build a ``function_response`` parts list for a tool result message."""
    if isinstance(content, list):
        text_chunks = [
            item.get('text', '')
            for item in content
            if isinstance(item, dict) and item.get('type') == 'text'
        ]
        payload: Any = '\n'.join(text_chunks)
    else:
        payload = content if content is not None else ''
    return [
        {
            'function_response': {
                'name': name or 'tool',
                'response': {'output': payload},
            }
        }
    ]


def convert_messages(
    messages: list[dict[str, Any]],
) -> tuple[str | None, list[dict[str, Any]], bool]:
    """Convert messages to Gemini format, extracting system instruction.

    Tool-call assistant messages and tool-result messages are emitted using
    native Gemini ``function_call`` / ``function_response`` parts so that
    Gemini 2.5 thinking models receive the ``thought_signature`` they require
    on subsequent turns.  Plain text messages keep the existing text-only path.

    Returns:
        (system_instruction_or_None, gemini_history_messages, caching_requested)
    """
    system_instruction: str | None = None
    gemini_messages: list[dict[str, Any]] = []
    caching_requested = False

    for m in messages:
        content = m.get('content', '')
        role_name = m.get('role', 'user')

        # Handle list-style content (from App's message serialization)
        text_parts = []
        if isinstance(content, list):
            for item in content:
                if isinstance(item, dict) and item.get('type') == 'text':
                    text_parts.append(item.get('text', ''))
                    if item.get('cache_prompt'):
                        caching_requested = True
            content_text = '\n'.join(text_parts)
        else:
            content_text = content if isinstance(content, str) else ''

        if role_name == 'system':
            if system_instruction:
                system_instruction += '\n\n' + content_text
            else:
                system_instruction = content_text
            continue

        # Tool-result messages -> function_response part on a 'user' turn.
        if role_name == 'tool':
            gemini_messages.append(
                {
                    'role': 'user',
                    'parts': _build_gemini_tool_response_parts(
                        m.get('name', ''),
                        content if isinstance(content, list) else content_text,
                    ),
                }
            )
            continue

        # Assistant messages with native tool_calls -> function_call parts on
        # a 'model' turn (preserving any thought_signature blobs).
        tool_calls = m.get('tool_calls') if role_name == 'assistant' else None
        if tool_calls:
            gemini_messages.append(
                {
                    'role': 'model',
                    'parts': _build_gemini_model_parts(content_text, tool_calls),
                }
            )
            continue

        role = 'model' if role_name == 'assistant' else 'user'
        gemini_messages.append(
            {'role': role, 'parts': [{'text': content_text}]}
        )

    return system_instruction, gemini_messages, caching_requested


_GEMINI_ALLOWED_SCHEMA_KEYS = {
    'defs',
    'maxLength',
    'default',
    'minimum',
    'max_length',
    'format',
    'propertyOrdering',
    'max_items',
    'min_items',
    'title',
    'min_length',
    'items',
    'max_properties',
    'description',
    'maxProperties',
    'any_of',
    'anyOf',
    'nullable',
    'property_ordering',
    'min_properties',
    'minLength',
    'example',
    'enum',
    'type',
    'pattern',
    'minProperties',
    'required',
    'minItems',
    'ref',
    'properties',
    'maxItems',
    'maximum',
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

        if k in ('properties', 'defs') and isinstance(v, dict):
            cleaned[k] = {
                pk: _strip_unsupported_schema_fields(pv) for pk, pv in v.items()
            }
        elif k in ('required', 'enum', 'default', 'example'):
            cleaned[k] = v
        else:
            cleaned[k] = _strip_unsupported_schema_fields(v)
    return cleaned


def map_tools_to_gemini(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Map OpenAI-style tool definitions to Gemini function_declarations format."""
    gemini_tools = []
    function_declarations = []

    for tool in tools:
        if tool.get('type') == 'function' and 'function' in tool:
            fn = tool['function']
            decl = {
                'name': fn['name'],
                'description': fn['description'],
            }
            if 'parameters' in fn:
                params = _strip_unsupported_schema_fields(fn['parameters'])
                decl['parameters'] = params
            function_declarations.append(decl)

    if function_declarations:
        gemini_tools.append({'function_declarations': function_declarations})

    return gemini_tools


def extract_generation_config(
    kwargs: dict[str, Any],
) -> tuple[str, dict[str, Any], list | None]:
    """Pop generation-config keys from *kwargs* and return (model_name, gen_config, tools)."""
    model_name = kwargs.pop('model', '')
    if '/' in model_name:
        model_name = model_name.split('/')[-1]

    tools_raw = kwargs.pop('tools', None)
    tools = map_tools_to_gemini(tools_raw) if tools_raw else None

    gen_cfg: dict[str, Any] = {}
    for src, dst in [
        ('temperature', 'temperature'),
        ('top_p', 'top_p'),
        ('top_k', 'top_k'),
        ('max_tokens', 'max_output_tokens'),
        ('stop', 'stop_sequences'),
    ]:
        if src in kwargs:
            gen_cfg[dst] = kwargs.pop(src)
    # Native Gemini SDK (ChatSession.send_message) does not support tool_choice.
    kwargs.pop('tool_choice', None)
    # Strip OpenAI/liteLLM-style passthrough fields unsupported by Gemini SDK.
    for unsupported_key in (
        'extra_body',
        'extra_headers',
        'response_format',
        'frequency_penalty',
        'presence_penalty',
        'logit_bias',
        'seed',
        'user',
        'reasoning_effort',
        'reasoning',
        'parallel_tool_calls',
        'metadata',
        'stream',
        'stream_options',
        'logprobs',
        'top_logprobs',
        'n',
        'timeout',
    ):
        kwargs.pop(unsupported_key, None)
    return model_name, gen_cfg, tools


def gemini_response_to_dict(response: Any) -> dict[str, Any] | None:
    """Best-effort conversion of Gemini SDK response to dict for stable parsing."""
    if isinstance(response, dict):
        return response

    to_dict = getattr(response, 'to_dict', None)
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
        for candidate in response_dict.get('candidates', []) or []:
            if not isinstance(candidate, dict):
                continue
            content = candidate.get('content', {})
            if not isinstance(content, dict):
                continue
            candidate_parts = content.get('parts')
            if candidate_parts:
                parts.extend(candidate_parts)

    if parts:
        return parts

    for candidate in getattr(response, 'candidates', []) or []:
        content = getattr(candidate, 'content', None)
        if content is None and isinstance(candidate, dict):
            content = candidate.get('content')

        candidate_parts = None
        if isinstance(content, dict):
            candidate_parts = content.get('parts')
        elif content is not None:
            candidate_parts = getattr(content, 'parts', None)

        if candidate_parts:
            parts.extend(candidate_parts)
    return parts


def coerce_fc_name_and_args(function_call: Any) -> tuple[str | None, Any]:
    """Extract function-call name and args from object/dict Gemini shapes."""
    if function_call is None:
        return None, None

    if isinstance(function_call, dict):
        return function_call.get('name'), function_call.get('args')

    return getattr(function_call, 'name', None), getattr(function_call, 'args', None)


def extract_tool_calls(response: Any) -> list[dict[str, Any]] | None:
    """Extract function call parts from a Gemini response.

    Each returned dict matches the OpenAI tool-call shape, with one extension:
    when the source part carries a ``thought_signature`` (Gemini 2.5 thinking
    models), it is preserved as raw bytes on the dict.  Replaying the signature
    verbatim on subsequent turns is required by the Gemini API.
    """
    tool_calls: list[dict[str, Any]] = []
    for part in iter_candidate_parts(response):
        fc = getattr(part, 'function_call', None)
        if fc is None and isinstance(part, dict):
            fc = part.get('function_call') or part.get('functionCall')

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

        # Gemini 2.5 thinking models attach an opaque thought_signature on
        # function_call parts.  Capture it (object or dict shape) so the
        # caller can replay it on later turns.
        thought_signature = getattr(part, 'thought_signature', None)
        if thought_signature is None and isinstance(part, dict):
            thought_signature = part.get('thought_signature') or part.get(
                'thoughtSignature'
            )

        entry: dict[str, Any] = {
            'id': f'gemini-{len(tool_calls)}',
            'type': 'function',
            'function': {
                'name': name,
                'arguments': json.dumps(args_dict),
            },
        }
        if isinstance(thought_signature, (bytes, bytearray)):
            entry['thought_signature'] = bytes(thought_signature)
        tool_calls.append(entry)

    return tool_calls if tool_calls else None


def _is_thought_part(part: Any) -> bool:
    """Return True if this response part is a reasoning/thought part.

    Gemini 2.5 thinking models set ``part.thought = True`` on thinking-only
    parts.  These must be excluded from regular content and handled separately.
    """
    if isinstance(part, dict):
        return bool(part.get('thought') or part.get('isThought'))
    return bool(getattr(part, 'thought', False))


def extract_text(response: Any) -> str:
    """Extract regular (non-thinking) text from a Gemini response.

    Thought parts (``part.thought == True``) are intentionally excluded here;
    use :func:`extract_thinking` to retrieve them separately.
    """
    text_parts: list[str] = []
    for part in iter_candidate_parts(response):
        if _is_thought_part(part):
            continue
        text = getattr(part, 'text', None)
        if text is None and isinstance(part, dict):
            text = part.get('text')
        if isinstance(text, str) and text.strip():
            text_parts.append(text)

    if text_parts:
        return '\n'.join(text_parts)

    response_text = getattr(response, 'text', '')
    return response_text if isinstance(response_text, str) else str(response_text or '')


def extract_thinking(response: Any) -> str:
    """Extract the model's reasoning/thinking text from a Gemini response.

    Returns a concatenation of all thought parts (``part.thought == True``).
    Returns an empty string for models that do not emit thinking content or
    when the response contains no thought parts.
    """
    thought_parts: list[str] = []
    for part in iter_candidate_parts(response):
        if not _is_thought_part(part):
            continue
        text = getattr(part, 'text', None)
        if text is None and isinstance(part, dict):
            text = part.get('text')
        if isinstance(text, str) and text.strip():
            thought_parts.append(text)
    return '\n'.join(thought_parts)


def extract_finish_reason(response: Any) -> str:
    response_dict = gemini_response_to_dict(response)
    if isinstance(response_dict, dict):
        candidates = response_dict.get('candidates') or []
        if candidates and isinstance(candidates[0], dict):
            reason = candidates[0].get('finishReason')
            if isinstance(reason, str) and reason:
                return reason

    for candidate in getattr(response, 'candidates', []) or []:
        reason = getattr(candidate, 'finish_reason', None)
        if isinstance(reason, str) and reason:
            return reason
        if isinstance(candidate, dict):
            reason = candidate.get('finish_reason') or candidate.get('finishReason')
            if isinstance(reason, str) and reason:
                return reason
    return ''


def extract_block_reason(response: Any) -> str:
    response_dict = gemini_response_to_dict(response)
    if isinstance(response_dict, dict):
        prompt_feedback = response_dict.get('promptFeedback') or response_dict.get(
            'prompt_feedback'
        )
        if isinstance(prompt_feedback, dict):
            reason = prompt_feedback.get('blockReason') or prompt_feedback.get(
                'block_reason'
            )
            if isinstance(reason, str) and reason:
                return reason

    feedback = getattr(response, 'prompt_feedback', None)
    if feedback is None:
        feedback = getattr(response, 'promptFeedback', None)
    reason = getattr(feedback, 'block_reason', None)
    if reason is None:
        reason = getattr(feedback, 'blockReason', None)
    return reason if isinstance(reason, str) else ''


def synthesize_empty_text(response: Any) -> str:
    block_reason = extract_block_reason(response)
    if block_reason:
        return (
            'I couldn’t provide a response because this request was blocked by safety '
            'filters. Please rephrase and try again.'
        )

    finish_reason = extract_finish_reason(response).upper()
    if finish_reason in {'SAFETY', 'RECITATION', 'BLOCKLIST'}:
        return (
            'I couldn’t provide a response for this request. Please try a clearer '
            'or safer phrasing and I’ll help.'
        )

    return (
        'I couldn’t generate a complete response this turn. Please resend your '
        'request and I’ll answer directly.'
    )


def ensure_non_empty_content(
    response: Any, content: str, tool_calls: list[dict[str, Any]] | None
) -> str:
    if content.strip() or tool_calls:
        return content
    return synthesize_empty_text(response)


def gemini_usage(response: Any) -> dict[str, int]:
    try:
        if hasattr(response, 'usage_metadata'):
            usage = response.usage_metadata
            return {
                'prompt_tokens': getattr(usage, 'prompt_token_count', 0),
                'completion_tokens': getattr(usage, 'candidates_token_count', 0),
                'total_tokens': getattr(usage, 'total_token_count', 0),
            }

        response_dict = gemini_response_to_dict(response)
        if response_dict and 'usageMetadata' in response_dict:
            usage = response_dict['usageMetadata']
            return {
                'prompt_tokens': usage.get('promptTokenCount', 0),
                'completion_tokens': usage.get('candidatesTokenCount', 0),
                'total_tokens': usage.get('totalTokenCount', 0),
            }

    except Exception:
        pass
    return {}
