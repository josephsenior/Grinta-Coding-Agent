"""Anthropic-specific LLM data adapters and mappers."""

import json
from typing import Any

from backend.core.logging.logger import app_logger as logger


def extract_tool_calls(
    content_blocks: list,
) -> tuple[str, list[dict[str, Any]] | None]:
    """Extract text and tool_use blocks from Anthropic response content.

    Returns:
        (text_content, tool_calls_or_None)
    """
    text_parts: list[str] = []
    tool_calls: list[dict[str, Any]] = []
    for block in content_blocks:
        block_type = getattr(block, 'type', None)
        if block_type == 'text':
            text_parts.append(block.text)
        elif block_type == 'tool_use':
            tool_calls.append(
                {
                    'id': block.id,
                    'type': 'function',
                    'function': {
                        'name': block.name,
                        'arguments': json.dumps(block.input)
                        if isinstance(block.input, dict)
                        else str(block.input),
                    },
                }
            )
    return '\n'.join(text_parts), tool_calls or None


def _apply_system_cache_control(
    system_content: Any, model: str, kwargs: dict[str, Any]
) -> Any:
    """Return system content with cache_control if the model supports prompt caching.

    When caching is supported, converts a plain string into the list-of-blocks
    format Anthropic requires and adds the ``prompt-caching-2024-07-31`` beta
    header.  Otherwise returns ``system_content`` unchanged.
    """
    from backend.inference.caching.prompt_caching import (
        model_supports_prompt_cache_hints,
    )

    if system_content is None:
        return None
    if model_supports_prompt_cache_hints(model):
        text = (
            system_content if isinstance(system_content, str) else str(system_content)
        )
        if 'betas' not in kwargs:
            kwargs['betas'] = ['prompt-caching-2024-07-31']
        return [{'type': 'text', 'text': text, 'cache_control': {'type': 'ephemeral'}}]
    return system_content


def prepare_kwargs(
    messages: list[dict[str, Any]], kwargs: dict[str, Any], default_model: str
) -> tuple[list, dict[str, Any]]:
    """Extract system message and set model for Anthropic calls."""
    system_msg = _collect_system_messages(messages)
    filtered = _normalize_messages([m for m in messages if m['role'] != 'system'])
    if 'model' not in kwargs:
        kwargs['model'] = default_model
    if system_msg is not None:
        model = kwargs.get('model', default_model)
        kwargs['system'] = _apply_system_cache_control(system_msg, model, kwargs)
    _normalize_tools(kwargs)
    # Mark the last tool definition with cache_control so Anthropic caches the
    # entire system + tools prefix.  Tool definitions are stable across turns,
    # making them ideal cache breakpoints (saves 3K-10K input tokens per call).
    _apply_tools_cache_control(kwargs)
    return filtered, kwargs


def _content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return '' if content is None else str(content)
    parts: list[str] = []
    for item in content:
        if isinstance(item, str):
            parts.append(item)
        elif isinstance(item, dict):
            text = item.get('text')
            if isinstance(text, str):
                parts.append(text)
    return '\n'.join(part for part in parts if part)


def _collect_system_messages(messages: list[dict[str, Any]]) -> str | None:
    """Combine all system messages for APIs that expose one system field."""
    parts: list[str] = []
    for message in messages:
        if not isinstance(message, dict) or message.get('role') != 'system':
            continue
        text = _content_to_text(message.get('content')).strip()
        if text:
            parts.append(text)
    return '\n\n'.join(parts) if parts else None


def _parse_tool_arguments(arguments: Any) -> dict[str, Any]:
    if isinstance(arguments, dict):
        return arguments
    if isinstance(arguments, str) and arguments.strip():
        try:
            parsed = json.loads(arguments)
        except json.JSONDecodeError:
            return {'arguments': arguments}
        if isinstance(parsed, dict):
            return parsed
        return {'arguments': parsed}
    return {}


def _is_valid_tool_call_id(tool_id: Any) -> bool:
    return isinstance(tool_id, str) and bool(tool_id.strip())


def _is_valid_tool_name(name: Any) -> bool:
    return isinstance(name, str) and bool(name.strip())


def _build_tool_use_block(
    tool_call: dict[str, Any],
) -> tuple[dict[str, Any] | None, str | None]:
    tool_id = tool_call.get('id')
    function = tool_call.get('function')
    if not _is_valid_tool_call_id(tool_id):
        return None, None
    if not isinstance(function, dict):
        return None, None
    name = function.get('name')
    if not _is_valid_tool_name(name):
        return None, None
    tool_name = str(name).strip()
    return (
        {
            'type': 'tool_use',
            'id': tool_id,
            'name': tool_name,
            'input': _parse_tool_arguments(function.get('arguments')),
        },
        tool_id,
    )


def _normalize_assistant_message(
    message: dict[str, Any],
    known_tool_ids: set[str],
) -> dict[str, Any] | None:
    tool_calls = message.get('tool_calls')
    if not isinstance(tool_calls, list) or not tool_calls:
        return message

    content_blocks: list[dict[str, Any]] = []
    text = _content_to_text(message.get('content')).strip()
    if text:
        content_blocks.append({'type': 'text', 'text': text})

    for tool_call in tool_calls:
        if not isinstance(tool_call, dict):
            continue
        block, tool_id = _build_tool_use_block(tool_call)
        if block is None or tool_id is None:
            continue
        known_tool_ids.add(tool_id)
        content_blocks.append(block)

    if not content_blocks:
        return None
    normalized = {k: v for k, v in message.items() if k != 'tool_calls'}
    normalized['role'] = 'assistant'
    normalized['content'] = content_blocks
    return normalized


def _normalize_tool_message(
    message: dict[str, Any],
    known_tool_ids: set[str],
) -> dict[str, Any]:
    tool_call_id = message.get('tool_call_id')
    content = _content_to_text(message.get('content'))
    tool_name = message.get('name')
    label = tool_name if isinstance(tool_name, str) and tool_name else 'tool'

    if isinstance(tool_call_id, str) and tool_call_id in known_tool_ids:
        result_content: list[dict[str, Any]] = []
        if content.strip():
            result_content.append({
                'type': 'tool_result',
                'tool_use_id': tool_call_id,
                'content': content,
            })
        else:
            result_content.append({
                'type': 'tool_result',
                'tool_use_id': tool_call_id,
                'content': f'[{label} completed]',
            })
        return {
            'role': 'user',
            'content': result_content,
        }

    return {
        'role': 'user',
        'content': f'[Unmatched tool result from {label}]\n{content}'.strip(),
    }


def _normalize_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    known_tool_ids: set[str] = set()
    for raw_message in messages:
        if not isinstance(raw_message, dict):
            continue  # type: ignore[unreachable]
        message = dict(raw_message)
        message.pop('tool_ok', None)
        role = message.get('role')
        if role == 'assistant':
            assistant_message = _normalize_assistant_message(message, known_tool_ids)
            if assistant_message is not None:
                normalized.append(assistant_message)
            continue
        if role == 'tool':
            normalized.append(_normalize_tool_message(message, known_tool_ids))
            continue
        normalized.append(message)
    return normalized


def _default_input_schema() -> dict[str, Any]:
    return {'type': 'object', 'properties': {}}


_SCHEMA_COMBINATORS = ('oneOf', 'allOf', 'anyOf')
_CONDITIONAL_KEYS = ('if', 'then', 'else')


def model_requires_anthropic_tool_schema(model: str) -> bool:
    """Return True when tool schemas must satisfy Anthropic JSON Schema rules."""
    if not model:
        return False

    from backend.inference.catalog.catalog_loader import (
        TRANSPORT_CLIENT_ANTHROPIC,
        resolve_transport_client,
    )

    if resolve_transport_client(model) == TRANSPORT_CLIENT_ANTHROPIC:
        return True

    lowered = model.lower()
    return (
        'anthropic/' in lowered or '/claude' in lowered or lowered.startswith('claude')
    )


def _merge_combinator_branches(branches: Any) -> dict[str, Any]:
    if not isinstance(branches, list):
        return {}

    merged_props: dict[str, Any] = {}
    merged_required: list[str] = []
    for branch in branches:
        if not isinstance(branch, dict):
            continue
        candidate = branch
        then_branch = branch.get('then')
        if 'if' in branch and isinstance(then_branch, dict):
            candidate = then_branch
        props = candidate.get('properties')
        if isinstance(props, dict):
            merged_props.update(props)
        required = candidate.get('required')
        if isinstance(required, list):
            merged_required.extend(str(item) for item in required)

    merged: dict[str, Any] = {}
    if merged_props:
        merged['properties'] = merged_props
    if merged_required:
        merged['required'] = list(dict.fromkeys(merged_required))
    return merged


def _sanitize_json_schema_node(schema: Any, *, at_root: bool) -> dict[str, Any]:
    if not isinstance(schema, dict) or not schema:
        return _default_input_schema() if at_root else {}

    normalized: dict[str, Any] = dict(schema)

    if at_root:
        for combinator in _SCHEMA_COMBINATORS:
            if combinator not in normalized:
                continue
            branches = normalized.pop(combinator)
            # Conditional allOf blocks (if/then) encode optional required fields
            # Anthropic cannot represent. oneOf/anyOf may define the base shape.
            if combinator in ('oneOf', 'anyOf') and not normalized.get('properties'):
                merged = _merge_combinator_branches(branches)
                for key, value in merged.items():
                    if key not in normalized:
                        normalized[key] = value

    for key in _CONDITIONAL_KEYS:
        normalized.pop(key, None)

    props = normalized.get('properties')
    if isinstance(props, dict):
        normalized['properties'] = {
            name: _sanitize_json_schema_node(prop, at_root=False)
            for name, prop in props.items()
        }

    items = normalized.get('items')
    if isinstance(items, dict):
        normalized['items'] = _sanitize_json_schema_node(items, at_root=False)
    elif isinstance(items, list):
        normalized['items'] = [
            _sanitize_json_schema_node(item, at_root=False)
            if isinstance(item, dict)
            else item
            for item in items
        ]

    if at_root:
        if not isinstance(normalized.get('type'), str) or not normalized.get('type'):
            normalized['type'] = 'object'
        if normalized.get('type') == 'object' and not isinstance(
            normalized.get('properties'), dict
        ):
            normalized['properties'] = {}

    return normalized


def _normalize_input_schema(schema: Any) -> dict[str, Any]:
    return _sanitize_json_schema_node(schema, at_root=True)


def _openai_tool_to_anthropic(tool: dict[str, Any]) -> dict[str, Any] | None:
    function = tool.get('function')
    if not isinstance(function, dict):
        return None
    name = function.get('name')
    if not isinstance(name, str) or not name.strip():
        return None

    converted: dict[str, Any] = {
        'name': name.strip(),
        'input_schema': _normalize_input_schema(function.get('parameters')),
    }
    description = function.get('description')
    if isinstance(description, str) and description.strip():
        converted['description'] = description
    cache_control = tool.get('cache_control')
    if cache_control is not None:
        converted['cache_control'] = cache_control
    return converted


def _anthropic_tool_to_anthropic(tool: dict[str, Any]) -> dict[str, Any] | None:
    name = tool.get('name')
    if not isinstance(name, str) or not name.strip():
        return None
    converted = dict(tool)
    converted['name'] = name.strip()
    converted['input_schema'] = _normalize_input_schema(converted.get('input_schema'))
    converted.pop('parameters', None)
    return converted


def _normalize_tool(tool: Any) -> dict[str, Any] | None:
    if not isinstance(tool, dict):
        return None
    if 'function' in tool:
        return _openai_tool_to_anthropic(tool)
    if 'name' in tool:
        return _anthropic_tool_to_anthropic(tool)
    return None


def _normalize_tools(kwargs: dict[str, Any]) -> None:
    tools = kwargs.get('tools')
    if tools is None:
        return
    if not isinstance(tools, list):
        logger.warning('Dropping Anthropic tools payload because it is not a list')
        kwargs.pop('tools', None)
        return

    normalized_tools: list[dict[str, Any]] = []
    dropped = 0
    for tool in tools:
        normalized = _normalize_tool(tool)
        if normalized is None:
            dropped += 1
            continue
        normalized_tools.append(normalized)

    if dropped:
        logger.warning(
            'Dropped %d invalid Anthropic tool definition(s) before provider request',
            dropped,
        )
    if normalized_tools:
        kwargs['tools'] = normalized_tools
    else:
        kwargs.pop('tools', None)


def _apply_tools_cache_control(kwargs: dict[str, Any]) -> None:
    """Add cache_control to the last tool definition for Anthropic prompt caching.

    Anthropic caches everything up to and including the last block with
    ``cache_control``.  By marking the final tool, the entire system message +
    tool definitions block is cached, saving significant input tokens on
    subsequent calls within the same session.
    """
    from backend.inference.caching.prompt_caching import (
        model_supports_prompt_cache_hints,
    )

    tools = kwargs.get('tools')
    if not tools or not isinstance(tools, list):
        return
    model = kwargs.get('model', '')
    if not model_supports_prompt_cache_hints(model):
        return
    last_tool = tools[-1]
    if isinstance(last_tool, dict):
        last_tool['cache_control'] = {'type': 'ephemeral'}
